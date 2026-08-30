"""M08：_build_rag_search 将覆盖模型绑定到 rewriter / reranker。"""

from types import SimpleNamespace

from venagent import bootstrap
from venagent.config import load_config


class _FixedModel:
    def __init__(self, label: str) -> None:
        self.label = label

    def invoke(self, _messages):
        return None


def _minimal_adapters() -> bootstrap._RepositoryAdapters:
    return bootstrap._RepositoryAdapters(
        conversation=SimpleNamespace(),
        runs=SimpleNamespace(),
        ownership=SimpleNamespace(),
        memory=SimpleNamespace(),
        document=SimpleNamespace(),
    )


def _service(config, rewrite_model, rerank_model):
    return bootstrap._build_rag_search(
        _minimal_adapters(),
        config,
        SimpleNamespace(client=None),
        SimpleNamespace(client=None),
        SimpleNamespace(driver=None, database="neo4j"),
        rewrite_model,
        rerank_model,
        embedding=None,
        kg_extractor=None,
    )


def test_rag_search_binds_override_models(tmp_path):
    config = load_config(
        project_root=tmp_path,
        environ={
            "LLM_PROVIDER": "openai",
            "LLM_API_KEY": "k",
            "LLM_MODEL": "main-model",
            "REWRITE_MODEL_MODEL": "rewrite-model",
            "RERANK_MODEL_MODEL": "rerank-model",
        },
    )
    main = _FixedModel("main")
    rewrite = _FixedModel("rewrite")
    rerank = _FixedModel("rerank")

    service = _service(config, rewrite, rerank)

    assert service is not None
    assert service._rewriter._model is rewrite
    assert service._reranker._model is rerank
    assert service._rewriter._model is not main
    assert service._reranker._model is not main


def test_rag_search_defaults_to_main_model(tmp_path):
    config = load_config(
        environ={
            "LLM_PROVIDER": "openai",
            "LLM_API_KEY": "k",
            "LLM_MODEL": "main-model",
        },
        project_root=tmp_path,
    )
    main = _FixedModel("main")

    service = _service(config, main, main)

    assert service is not None
    assert service._rewriter._model is main
    assert service._reranker._model is main
