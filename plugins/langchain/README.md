# saaf-langchain

```python
from saaf_langchain import with_saaf, mask_documents

chain = prompt | with_saaf(ChatOpenAI())  # masks inputs, restores outputs and tool-call args

# RAG: mask before embedding; keyed-HMAC tokens are stable across chunks and runs
docs = mask_documents(loader.load(), key=bytes.fromhex(os.environ["SAAF_INDEX_KEY"]))
```

Keep the index key secret. Anyone holding it can test guesses against the tokens.
