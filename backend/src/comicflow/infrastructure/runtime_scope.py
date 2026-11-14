from contextvars import ContextVar

from comicflow.infrastructure.generation_state import GenerationStateStore
from comicflow.infrastructure.memory import Runtime
from comicflow.production.pipeline import ProductionPipeline
from comicflow.providers.runtime_config import ProviderConfigStore


class RuntimeScope:
    def __init__(self, base: Runtime) -> None:
        self.base = base
        self.current: ContextVar[Runtime] = ContextVar("comicflow_request_runtime", default=base)

    @property
    def pipeline(self) -> ProductionPipeline:
        return self.current.get().pipeline

    @property
    def provider_config_store(self) -> ProviderConfigStore:
        return self.base.provider_config_store

    @property
    def generation_state_store(self) -> GenerationStateStore:
        return self.base.generation_state_store
