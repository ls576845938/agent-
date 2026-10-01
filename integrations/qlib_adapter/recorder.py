"""Local Qlib recorder with explicit lineage instead of repo/env/argv harvesting.

Qlib 0.9.7's default recorder executes unscoped git diff/status and logs environment
variables. Research lineage is instead recorded in our hashed run metadata.
"""
from datetime import datetime
import mlflow
from qlib.utils.paral import AsyncCaller
from qlib.workflow.recorder import MLflowRecorder, Recorder
from qlib.workflow.exp import MLflowExperiment
from qlib.workflow.expm import MLflowExpManager


class ResearchRecorder(MLflowRecorder):
    def start_run(self):
        mlflow.set_tracking_uri(self.uri)
        run = mlflow.start_run(self.id, self.experiment_id, self.name)
        self.id = run.info.run_id
        self._artifact_uri = run.info.artifact_uri
        self.start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.status = Recorder.STATUS_R
        self.async_log = AsyncCaller()
        return run


class ResearchExperiment(MLflowExperiment):
    def create_recorder(self, recorder_name=None):
        return ResearchRecorder(self.id, self._uri, recorder_name or self._default_rec_name)


class ResearchExpManager(MLflowExpManager):
    def _get_exp(self, experiment_id=None, experiment_name=None):
        experiment = super()._get_exp(experiment_id, experiment_name)
        return ResearchExperiment(experiment.id, experiment.name, self.uri)

    def create_exp(self, experiment_name=None):
        experiment = super().create_exp(experiment_name)
        return ResearchExperiment(experiment.id, experiment.name, self.uri)
