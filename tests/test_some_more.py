import logging
import os
import subprocess
import time
from pathlib import Path
from tempfile import NamedTemporaryFile

import requests
import yaml

import pytest
from pykube import Pod

# from .giantswarm_cluster_gsctl import GiantswarmClusterGsctl
# from .kind_cluster import KindCluster

from pytest_kube import KindCluster, GiantswarmClusterGsctl, ExistingCluster


skip = pytest.mark.skipif("True")


cluster_setting_godsmack = {
    "cluster_cls": GiantswarmClusterGsctl,
    "name": "pytest-godsmack",
    # "endpoint": "https://api.g8s.ghost.westeurope.azure.gigantic.io",
    "endpoint": "https://api.g8s.godsmack.westeurope.azure.gigantic.io",
    "email": os.environ.get("GSCTL_EMAIL", ""),
    "password": os.environ.get("GSCTL_PASSWORD"),
    "config": {
        "owner": "giantswarm",
        "scaling": {"min": 3, "max": 3},
        "workers": [{"azure": {"vm_size": "Standard_D4s_v3"}}],
    },
}

cluster_setting_gorgoth = {
    "cluster_cls": GiantswarmClusterGsctl,
    "name": "pytest-gorgoth",
    # "endpoint": "https://api.g8s.geckon.gridscale.kvm.gigantic.io",
    "endpoint": "https://api.g8s.gorgoth.gridscale.kvm.gigantic.io",
    "email": os.environ.get("GSCTL_EMAIL", ""),
    "password": os.environ.get("GSCTL_PASSWORD"),
    # "config_file": Path(__file__).parent / "giantswarm-cluster-kvm.yaml",
    "config": {
        # "release": "11.3.1",
        "owner": "giantswarm",
        "scaling": {"min": 3, "max": 3},
        "workers": [
            {
                "memory": {"size_gb": 16},
                "cpu": {"cores": 8},
                "storage": {"size_gb": 100},
            }
        ],
    },
}

# cluster_setting = {
#     "name": "pytest-cluster",
#     "endpoint": "https://api.g8s.gauss.eu-central-1.aws.gigantic.io",
#     "email": os.environ['GSCTL_EMAIL'],
#     "password": os.environ['GSCTL_PASSWORD'],
#     "config_file": Path(__file__).parent / "giantswarm-cluster-aws.yaml"
# }

cluster_setting_kind = {
    "cluster_cls": KindCluster,
    "name": "pytest-kind12",
    # FIXME config wins over config_file
    # "config": {
    # }
    "config_file": Path(__file__).parent / "kind-config.yaml",
}

cluster_setting_existing1 = {
    "cluster_cls": ExistingCluster,
    "name": "pytest-existing1",
    
    # "config_file": Path(__file__).parent / "kind-config.yaml",
    # "kubeconfig_path": Path(".") / ".pytest-kube" / "existing1-config.yaml",
    # "kubeconfig_path": Path(__file__).parent / "kubeconfig.yaml"
    "kubeconfig_path": Path(".") / ".pytest-kube" / "kubeconfig_minikube"
}


cluster_setting = cluster_setting_existing1


def test_kubernetes_version(cluster_create):
    cluster = cluster_create(**cluster_setting)

    # assert cluster.api.version == ("1", "16")
    assert cluster.api.version in [("1", "16"), ("1", "17"), ("1", "18")]


@skip
def test_kubernetes_chart_museum(cluster_create):
    cluster = cluster_create(**cluster_setting)

    cluster.kubectl("apply", "-f", Path(__file__).parent / "chart-museum.yaml")
    cluster.kubectl("-n", "giantswarm", "rollout", "status", "deployment/chart-museum")
    # TODO
    assert cluster.api.version in [("1", "16"), ("1", "17"), ("1", "18")]


# @skip
def test_helm(cluster_create):
    cluster = cluster_create(**cluster_setting)

    assert "The Kubernetes package manager" in subprocess.check_output(
        ["helm", "--help"], encoding="utf-8"
    )

    chart_path = Path(".") / "helm" / "efk-stack-app"
    # subprocess.check_output(
    #     ["helm", "template", "helm-test-efk", chart_path], encoding="utf-8"
    # )

    with NamedTemporaryFile(mode="w+") as tmp:
        helm_template_cmd = f"""
            helm template helm-test-efk {chart_path}
                --values={Path(__file__).parent / "values-one-node.yaml"}
        """
        rendered_manifests = subprocess.check_output(
            helm_template_cmd.split(), encoding="utf-8"
        )

        resources = list(yaml.safe_load_all(rendered_manifests))
        yaml.dump_all(documents=resources, stream=tmp)
        cluster.kubectl("apply", "-f", tmp.name)

    namespace = "default"

    cluster.kubectl(
        *f"""
        -n {namespace} rollout status statefulset/helm-test-efk-opendistro-es-master
    """.split()
    )

    # cluster.kubectl(
    #     "-n",
    #     namespace,
    #     "rollout",
    #     "status",
    #     "deployment/helm-test-efk-opendistro-es-kibana",
    # )

    # FIXME wait for answer on servide port?

    # all_masters_initialized = False

    # while not all_masters_initialized:
    #     all_masters_initialized = True

    #     # does not work if cluster is already up for longer time..
    #     for pod in Pod.objects(cluster.api).filter(selector="statefulset.kubernetes.io/pod-name=helm-test-efk-opendistro-es-master-0"):
    #         # assert "Node 'helm-test-efk-opendistro-es-master-0' initialized" in pod.logs()
    #         if not "Node 'helm-test-efk-opendistro-es-master-0' initialized" in pod.logs():
    #             all_masters_initialized = False
    #             time.sleep(2)

    with cluster.port_forward(
        "service/helm-test-efk-opendistro-es-client-service", 9200
    ) as port:
        r = requests.get(f"http://localhost:{port}/", auth=("admin", "admin"))

        r.raise_for_status()
        assert "You Know, for Search" in r.text


# @skip
def test_elasticsearch_unauthorized(cluster_create):
    cluster = cluster_create(**cluster_setting)

    with cluster.port_forward(
        "service/helm-test-efk-opendistro-es-client-service", 9200
    ) as port:
        r = requests.get(f"http://localhost:{port}/")

        # with pytest.raises(requests.exceptions.HTTPError):
        #     r.raise_for_status()

        assert r.status_code == 401
