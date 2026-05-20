FROM public.ecr.aws/lambda/python:3.12

WORKDIR ${LAMBDA_TASK_ROOT}

# Install dependencies
COPY api/requirements.txt ./
RUN pip install -r requirements.txt --no-cache-dir

# Pre-bake ONNX embedding model into image — no runtime HuggingFace downloads
# Model lands in /root/.cache/huggingface/hub/ which is part of the image layer
RUN python -c "\
from sentence_transformers import SentenceTransformer; \
SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2', backend='onnx')"

# Copy source — tools/ and api/ only, no NiceGUI app or local DB
COPY tools/ ./tools/
COPY api/ ./api/

# Lambda invokes this handler
CMD ["api.main.handler"]
