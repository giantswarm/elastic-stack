FROM python:3.9-slim
RUN pip install pytest-helm-charts

CMD pytest

# docker build -t local/pytest-helm-charts .
#
# run from git-root:
# docker run -it \
#   --network host \
#   --mount type=bind,source=$KUBECONFIG,target=/root/.kube/config \
#   --mount type=bind,source=$PWD,target=$PWD \
#   --workdir $PWD \
#   local/pytest-helm-charts
