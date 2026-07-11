FROM python:3.13-slim

WORKDIR /workspace
COPY . .

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -e ".[dev,mutation]"

CMD ["sh", "-c", "mutmut run --max-children 2 && mutmut results"]
