# 火山方舟 API 协议参考（与本项目对齐的接口示例）

> 真实 API Key 不要提交到仓库；生产请用 `config/config.local.yaml`、环境变量或密钥管理服务。
> 占位符：`$ARK_API_KEY`

`final/config/config.yaml` 只保留无秘密模板。需要连接本地基础设施时，请复制为被忽略的
`final/config/config.local.yaml`，填入密码和 API Key，并通过 `AGI_CONFIG` 指向该文件；不要修改
或提交模板中的真实凭据。Compose 的数据库密码也必须通过环境变量或被忽略的 `.env` 文件提供。

## 多模态向量化

```bash
curl https://ark.cn-beijing.volces.com/api/v3/embeddings/multimodal \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $ARK_API_KEY" \
  -d '{
    "model": "ep-xxxxxxxx-xxxxx",
    "input": [
      {"type": "text", "text": "天很蓝，海很深"},
      {"type": "image_url", "image_url": {"url": "https://example.com/view.jpeg"}}
    ]
  }'
```

返回结构：`data` 是单对象（不是数组），`data.embedding` 即向量。

## 对话模型（OpenAI 兼容 Chat Completions）

```bash
curl https://ark.cn-beijing.volces.com/api/v3/chat/completions \
  -H "Authorization: Bearer $ARK_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "ep-xxxxxxxx-xxxxx",
    "messages": [
      {"role": "system", "content": "你是一个乐于助人的助手"},
      {"role": "user", "content": "你好"}
    ],
    "temperature": 0.7
  }'
```

`internal/llm/llm.py` 走的就是这个协议；如果 `embed_api_url` 里包含 `/embeddings/multimodal`，会自动切到上面的多模态格式。
