import dagster as dg
from dagster_dask import dask_executor
from dagster_aws.s3 import s3_pickle_io_manager, s3_resource  # Added s3_resource

# dagster_dask's "kube" cluster type does `from dask_kubernetes import KubeCluster`,
# which dask-kubernetes >= 2024 no longer exports at top level. Point it at the
# operator-based KubeCluster (creates a DaskCluster CR for the dask operator).
import asyncio
import time

import dask_kubernetes
from dask_kubernetes.operator import KubeCluster as _OperatorKubeCluster
from dask_kubernetes.operator._objects import DaskCluster


class KubeCluster(_OperatorKubeCluster):
    """Work around a dask-kubernetes-operator 2026.3.0 status race.

    The scheduler Service handler patches status.phase=Running, then the
    create_components handler finishes and overwrites it with Pending. A
    ClusterIP service never changes status again, so the phase sticks at
    Pending and the stock client times out waiting for Running. The operator
    only sets Pending after creating all components, and the client waits for
    the scheduler pod/service/comm next anyway, so accept either phase.
    """

    async def _wait_for_controller(self):
        start = time.time()
        cluster = await DaskCluster.get(self.name, namespace=self.namespace, timeout=30)
        while start + self._resource_timeout > time.time():
            await cluster.async_refresh()
            if cluster.raw.get("status", {}).get("phase") in ("Pending", "Running"):
                return
            await asyncio.sleep(0.25)
        raise TimeoutError(
            f"Dask Cluster resource not actioned after {self._resource_timeout} seconds, "
            "is the Dask Operator running?"
        )


dask_kubernetes.KubeCluster = KubeCluster

@dg.op
def generate_data():
    return list(range(100))

@dg.op
def compute_squares(numbers):
    import dask.bag as db
    return db.from_sequence(numbers).map(lambda x: x ** 2).compute()

@dg.job(
    executor_def=dask_executor,
    resource_defs={
        "io_manager": s3_pickle_io_manager,
        "s3": s3_resource
    }
)
def test_dask_operator_job():
    compute_squares(generate_data())

defs = dg.Definitions(jobs=[test_dask_operator_job])

