import subprocess
import logging
from pathlib import Path
from tempfile import NamedTemporaryFile
import random

import requests
import yaml
# from pykube import Pod
import pykube
import pytest

from functools import partial
import time

from contextlib import contextmanager
from typing import Generator, Union

from .cluster import Cluster

import json


class GiantswarmCluster(Cluster):
    def __init__(self, name: str = None):
        self.name = name

    def create(
        self, 
        name,
        endpoint,
        email,
        password,
        config_file: Union[str, Path] = None):
        """Create the cluster if it does not exist (otherwise re-use)"""

        self.name = name
        self.endpoint = endpoint
        self.email = email
        self.password = password
        self.owner = "giantswarm"
        self.id = None


        login_cmd = f"""
            gsctl login {self.email}
                --endpoint={self.endpoint}
                --password={self.password}
        """
        # subprocess.run(login_cmd.split(), encoding="utf-8", check=True)
        out = subprocess.check_output(login_cmd.split(), encoding="utf-8")

        list_cmd = f"""
            gsctl list clusters
                --output=json
        """
        out = subprocess.check_output(list_cmd.split(), encoding="utf-8")

        cluster_exists = False

        if json.loads(out):
            for cluster in json.loads(out):
                if cluster["name"] == self.name:
                    cluster_exists = True

        if not cluster_exists:
            logging.info(f"Creating cluster {self.name}..")

            create_cmd = f"""
                gsctl create cluster
                    --name={self.name}
                    --owner={self.owner}
                    --file={config_file}
            """
            subprocess.run(create_cmd.split(), check=True)
            cluster_exists = True

        out = subprocess.check_output(list_cmd.split(), encoding="utf-8")

        for cluster in json.loads(out):
            if cluster["name"] == self.name:
                self.id = cluster["id"]
        
        kubeconfig_cmd = f"""
            gsctl create kubeconfig
                --ttl=1h
                --certificate-organizations=system:masters
                --cluster={self.id}
                --description=pytest
        """
        subprocess.run(kubeconfig_cmd.split(), encoding="utf-8", check=True)

        cluster_ready = False
        while not cluster_ready:
            cp = subprocess.run(["kubectl", "cluster-info"])
            if not cp.returncode:
                cluster_ready = True
            else:
                time.sleep(2)

        config = pykube.KubeConfig.from_file("/root/.kube/config")
        self.api = pykube.HTTPClient(config)


    # not implemented
    def load_docker_image(self, docker_image: str):
        pass


    def kubectl(self, *args: str, **kwargs) -> str:
        """Run a kubectl command against the cluster and return the output as string"""
        # self.ensure_kubectl()
        return subprocess.check_output(
            ["kubectl", *args],
            # env={"KUBECONFIG": str(self.kubeconfig_path)},
            encoding="utf-8",
            **kwargs,
        )

    # # not yet implemented
    # @contextmanager
    # def port_forward(
    #     self,
    #     service_or_pod_name: str,
    #     remote_port: int,
    #     *args,
    #     local_port: int = None,
    #     retries: int = 10,
    # ) -> Generator[int, None, None]:
    #     pass

    def delete(self):
        """Delete the Giant Swarm cluster ("kind delete cluster")"""
        logging.info(f"Deleting cluster {self.name}..")
        subprocess.run(
            ["gsctl", "delete", "cluster", "--force", self.id],
            check=True,
        )