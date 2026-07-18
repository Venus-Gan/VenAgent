"""Bootstrap 组合根所需的显式依赖边界。"""

from dataclasses import dataclass
from typing import Callable, TypeAlias

from venagent.infrastructure.config import AppConfig


InfrastructureFactory: TypeAlias = Callable[[AppConfig], object]
ApplicationFactory: TypeAlias = Callable[[AppConfig, object], object]
AppFactory: TypeAlias = Callable[[AppConfig, object, object], object]
AppShellFactory: TypeAlias = Callable[[], object]


@dataclass(frozen=True, slots=True)
class BootstrapDependencies:
    """Bootstrap 完成后交给入口层的运行时依赖集合。"""

    config: AppConfig
    infrastructure: object
    application: object
    app: object


@dataclass(frozen=True, slots=True)
class DependencyContainer:
    """显式依赖工厂集合，不承担 service locator 或资源创建职责。"""

    config: AppConfig
    infrastructure_factory: InfrastructureFactory
    application_factory: ApplicationFactory
    app_factory: AppFactory
    app_shell_factory: AppShellFactory | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.config, AppConfig):
            raise TypeError("config must be an AppConfig instance")
        factories = (
            ("infrastructure_factory", self.infrastructure_factory),
            ("application_factory", self.application_factory),
            ("app_factory", self.app_factory),
        )
        for name, factory in factories:
            if not callable(factory):
                raise TypeError(f"{name} must be callable")
        if self.app_shell_factory is not None and not callable(self.app_shell_factory):
            raise TypeError("app_shell_factory must be callable")
