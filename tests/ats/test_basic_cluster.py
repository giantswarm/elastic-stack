"""This module shows some very basic examples of how to use fixtures in pytest-helm-charts.
"""
import datetime
import logging
from contextlib import contextmanager
from typing import Dict, List, Optional

import pykube
import pytest
from pytest_helm_charts.fixtures import Cluster
from pytest_helm_charts.utils import (
    wait_for_stateful_sets_to_run,
    create_job_and_run_to_completion,
    make_job_object,
    ensure_namespace_exists,
)

logger = logging.getLogger(__name__)

app_name = "efk-stack-app"
client_service_base_url = "http://admin:admin@opendistro-es-client-service:9200"
namespace_name = "default"
catalog_name = "chartmuseum"

timeout: int = 360


@contextmanager
def delete_logs_scope(kube_cluster: Cluster):
    yield
    delete_logs(kube_cluster.kube_client)


@pytest.mark.smoke
def test_api_working(kube_cluster: Cluster) -> None:
    """Very minimalistic example of using the [kube_cluster](pytest_helm_charts.fixtures.kube_cluster)
    fixture to get an instance of [Cluster](pytest_helm_charts.clusters.Cluster) under test
    and access its [kube_client](pytest_helm_charts.clusters.Cluster.kube_client) property
    to get access to Kubernetes API of cluster under test.
    Please refer to [pykube](https://pykube.readthedocs.io/en/latest/api/pykube.html) to get docs
    for [HTTPClient](https://pykube.readthedocs.io/en/latest/api/pykube.html#pykube.http.HTTPClient).
    """
    assert kube_cluster.kube_client is not None
    assert len(pykube.Node.objects(kube_cluster.kube_client)) >= 1


@pytest.mark.smoke
def test_cluster_info(kube_cluster: Cluster, cluster_type: str, chart_extra_info: Dict[str, str]) -> None:
    """Example shows how you can access additional information about the cluster the tests are running on"""
    logger.info(f"Running on cluster type {cluster_type}")
    key = "external_cluster_type"
    if key in chart_extra_info:
        logger.info(f"{key} is {chart_extra_info[key]}")
    assert kube_cluster.kube_client is not None
    assert cluster_type != ""


# scope "module" means this is run only once, for the first test case requesting! It might be tricky
# if you want to assert this multiple times
@pytest.fixture(scope="module")
def efk_stateful_sets(kube_cluster: Cluster) -> List[pykube.StatefulSet]:
    return wait_for_efk_stateful_sets(kube_cluster)


def wait_for_efk_stateful_sets(kube_cluster: Cluster) -> List[pykube.StatefulSet]:
    stateful_sets = wait_for_stateful_sets_to_run(
        kube_cluster.kube_client,
        [f"{app_name}-opendistro-es-data", f"{app_name}-opendistro-es-master"],
        namespace_name,
        timeout,
    )
    return stateful_sets


# when we start the tests on circleci, we have to wait for EFK API to be available, hence
# this additional delay and retries
@pytest.mark.smoke
@pytest.mark.flaky(reruns=5, reruns_delay=10)
def test_pods_available(kube_cluster: Cluster, efk_stateful_sets: List[pykube.StatefulSet]):
    for s in efk_stateful_sets:
        assert int(s.obj["status"]["readyReplicas"]) > 0


@pytest.mark.functional
def test_masters_green(kube_cluster: Cluster, efk_stateful_sets: List[pykube.StatefulSet]):
    masters = [s for s in efk_stateful_sets if s.name == f"{app_name}-opendistro-es-master"]
    assert len(masters) == 1

    create_job_and_run_to_completion(
        kube_cluster.kube_client,
        namespace_name,
        make_job_object(
            kube_cluster.kube_client,
            "check-efk-green-",
            namespace_name,
            [
                "sh",
                "-c",
                # "wget -O - -q " f"{client_service_base_url}/_cat/health" " | grep green",
                "wget -O - -q " f"{client_service_base_url}/_cluster/health" " | grep green",
            ],
        ),
        timeout_sec=timeout,
    )


def generate_logs(
    kube_client: pykube.HTTPClient, logs_namespace: str, range_start: int = 1, range_end: int = 100
) -> pykube.Job:
    gen_job = create_job_and_run_to_completion(
        kube_client,
        logs_namespace,
        make_job_object(
            kube_client,
            "generate-logs-",
            logs_namespace,
            [
                "sh",
                "-c",
                f'seq {range_start} {range_end} | xargs printf "generating-logs-ding-dong-%03d\n"',
            ],
            restart_policy="Never",
            backoff_limit=0,
        ),
        timeout_sec=timeout,
    )
    flush_index(kube_client)
    return gen_job


def run_shell_against_efk(
    kube_client: pykube.HTTPClient, pod_name_prefix: str, namespace: str, command: str
) -> pykube.Job:
    return create_job_and_run_to_completion(
        kube_client,
        namespace,
        make_job_object(
            kube_client,
            pod_name_prefix,
            namespace,
            [
                "sh",
                "-c",
                command,
            ],
            image="docker.io/giantswarm/tiny-tools:3.10",
        ),
        timeout_sec=timeout,
    )


def query_logs(kube_client: pykube.HTTPClient, expected_no_log_entries_lower_bound: int) -> pykube.Job:
    command = (
        f"curl -s '{client_service_base_url}/_search?q=ding-dong&size=1000' "  # query more than we're expecting
        f"| jq --exit-status '.hits.total.value == {expected_no_log_entries_lower_bound}'"
    )
    return run_shell_against_efk(kube_client, "query-logs-", namespace_name, command)


def flush_index(kube_client: pykube.HTTPClient) -> pykube.Job:
    command = f"curl '{client_service_base_url}/_flush'"
    return run_shell_against_efk(kube_client, "flush-index-", namespace_name, command)


def delete_logs(kube_client: pykube.HTTPClient, index_date: Optional[datetime.datetime] = None) -> pykube.Job:
    # FIXME: This index name generation will work only for data generated on the same single day!
    # Better way to do it is to check index names by running
    # curl -s 'http://admin:admin@127.0.0.1:9200/_search?q=ding-dong&size=1000' | jq '[.hits.hits[]._index] | unique'
    fluentd_index_date = index_date if index_date is not None else datetime.datetime.now()
    index_name = f"fluentd-{fluentd_index_date.strftime('%Y.%m.%d')}"
    command = f"curl -X DELETE '{client_service_base_url}/{index_name}'"
    return run_shell_against_efk(kube_client, "delete-logs-", namespace_name, command)


@pytest.mark.functional
@pytest.mark.usefixtures("efk_stateful_sets")
def test_logs_are_picked_up(kube_cluster: Cluster) -> None:
    # create a new namespace
    # fluentd is configured to ignore certain namespaces
    logs_ns_name = "logs-ns"
    ensure_namespace_exists(kube_cluster.kube_client, logs_ns_name)

    with delete_logs_scope(kube_cluster):
        generate_logs(kube_cluster.kube_client, logs_ns_name)
        query_logs(kube_cluster.kube_client, expected_no_log_entries_lower_bound=100)


@pytest.mark.functional
@pytest.mark.usefixtures("efk_stateful_sets")
def test_can_survive_pod_restart(kube_cluster: Cluster, efk_stateful_sets: List[pykube.StatefulSet]) -> None:
    logs_ns_name = "logs-ns"
    ensure_namespace_exists(kube_cluster.kube_client, logs_ns_name)

    with delete_logs_scope(kube_cluster):
        generate_logs(kube_cluster.kube_client, logs_ns_name)
        query_logs(kube_cluster.kube_client, expected_no_log_entries_lower_bound=100)

        # find 1st pod of each of the core stateful sets, then delete it
        pods_to_delete = []
        for sts in efk_stateful_sets:
            pod_selector = sts.obj["spec"]["selector"]
            pods = pykube.Pod.objects(kube_cluster.kube_client).filter(
                namespace=namespace_name,
                selector=pod_selector["matchLabels"],
            )
            pods_to_delete.append(pykube.Pod(kube_cluster.kube_client, pods.response["items"][0]))
        for pod in pods_to_delete:
            pod.delete()

        # wait for pods to get back up
        wait_for_efk_stateful_sets(kube_cluster)

        # assert again
        generate_logs(kube_cluster.kube_client, logs_ns_name, range_start=101, range_end=200)
        query_logs(kube_cluster.kube_client, 200)


@pytest.mark.functional
@pytest.mark.usefixtures("efk_stateful_sets")
def test_pdbs_deployed(kube_cluster: Cluster) -> None:
    pdbs = pykube.PodDisruptionBudget.objects(kube_cluster.kube_client)
    pdb_names = [pdb.metadata["name"] for pdb in pdbs]
    assert pdb_names == [
        f"{app_name}-opendistro-es-client-pdb",
        f"{app_name}-opendistro-es-data-pdb",
        f"{app_name}-opendistro-es-master-pdb"
    ]
    for pdb in pdbs:
        if pdb.metadata["name"] == f"{app_name}-opendistro-es-client-pdb":
            assert pdb.obj["spec"]["maxUnavailable"] == 1
            assert pdb.obj["status"]["disruptionsAllowed"] == 1
            assert pdb.obj["status"]["desiredHealthy"] == 1
            assert pdb.obj["status"]["currentHealthy"] == 2
        else:
            assert pdb.obj["spec"]["maxUnavailable"] == 1
            assert pdb.obj["status"]["disruptionsAllowed"] == 1
            assert pdb.obj["status"]["desiredHealthy"] == 2
            assert pdb.obj["status"]["currentHealthy"] == 3
