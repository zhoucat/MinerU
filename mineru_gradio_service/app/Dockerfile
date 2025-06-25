# Dockerfile for the Gradio Application

# Use a Python base image
FROM python:3.10-slim

# Set the working directory in the container
WORKDIR /opt/app

# Copy the application code (app directory and src directory)
# First, copy only requirements to leverage Docker cache
COPY ./requirements.txt /opt/app/requirements.txt

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
# This includes the Gradio app UI files and the src/mineru library
COPY ./app /opt/app/app
COPY ./src /opt/app/src

# Make port 7860 available to the world outside this container (Gradio default port)
EXPOSE 7860

# Define environment variable for Python path if needed, though direct imports should work with this structure.
# ENV PYTHONPATH "${PYTHONPATH}:/opt/app"

# Command to run the Gradio application
# The app.py is now inside /opt/app/app/
CMD ["python", "app/app.py"]
