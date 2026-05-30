# anyagent Python 3.12 CI Image

This image backs the Yunxiao `anyagent build` pipeline:

```text
registry.cn-beijing.aliyuncs.com/lyriktrip/python:anyagent-ci-py312-amd64
```

Build and push:

```bash
docker build --platform linux/amd64 \
  -t registry.cn-beijing.aliyuncs.com/lyriktrip/python:anyagent-ci-py312-amd64 \
  docker/anyagent-ci-py312

docker push registry.cn-beijing.aliyuncs.com/lyriktrip/python:anyagent-ci-py312-amd64
```

The image intentionally includes `rustc` and `cargo` because
`tests/contract/test_second_runtime_poc.py` gates the Rust reference runtime
PoC in CI.
