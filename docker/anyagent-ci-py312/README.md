# anyagent Python 3.12 CI Image

This image was the runner for the retired Yunxiao `anyagent build` pipeline
(`.yunxiao/flow.anyagent.yml`). SDK release builds now run on GitHub-hosted
runners in `.github/workflows/ci.yml`.

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

The Rust toolchain was removed together with the Rust second-runtime PoC
(2026-10-07); the published tag still contains it until the image is rebuilt.
