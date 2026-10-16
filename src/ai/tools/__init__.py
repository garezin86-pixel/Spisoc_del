from src.ai.registry import ToolRegistry


def register_all(registry: ToolRegistry) -> None:
    from src.ai.tools import crm, tasks

    crm.register(registry)
    tasks.register(registry)
