## 🔴 降级透明化：LLM降级必须明确告知
当 `llm_bridge` 使用fallback时（delegate/LM Studio/Ollama全部不可用），
**必须在输出中包含**：
```
[⚠️ LLM不可用，使用预设规则/降级方案]
```
禁止静默降级。每个输出必须让格林主人知道用的是LLM还是规则。
