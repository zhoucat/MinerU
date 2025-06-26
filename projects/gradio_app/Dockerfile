# Use an official Python runtime as a parent image
FROM python:3.10-slim

# Set the working directory in the container
WORKDIR /app

# Copy the specific project directory and the mineru library
COPY ./projects/gradio_app /app/projects/gradio_app
COPY ./mineru /app/mineru
COPY ./pyproject.toml /app/pyproject.toml
COPY ./mineru.template.json /app/mineru.template.json
COPY ./README.md /app/README.md
COPY ./LICENSE.md /app/LICENSE.md
COPY ./SECURITY.md /app/SECURITY.md
COPY ./MinerU_CLA.md /app/MinerU_CLA.md


# Copy the requirements file for the gradio app
COPY ./projects/gradio_app/requirements.txt /app/projects/gradio_app/requirements.txt

# Install system dependencies that might be needed by opencv or other libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
# Install the main package (which should include mineru)
# Assuming the root of the repository has a setup.py or pyproject.toml that defines the mineru package
# If mineru is not meant to be installed as a package, this might need adjustment
RUN pip install --no-cache-dir -e .[full]
# Install dependencies for the gradio app
RUN pip install --no-cache-dir -r /app/projects/gradio_app/requirements.txt


# Make port 7860 available to the world outside this container
EXPOSE 7860

# Define environment variable
ENV GRADIO_SERVER_NAME="0.0.0.0"

# Set the default command to run the app
# Adjust the path to app.py as necessary based on the WORKDIR and COPY commands
CMD ["python", "/app/projects/gradio_app/app.py"]
