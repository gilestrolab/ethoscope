# Use an official Python runtime as a parent image
FROM python:3

# Clone the repository from GitHub
RUN apt-get update && \
    apt-get install -y git host nano

RUN mkdir -p /opt/ethoscope_resources
COPY ./pa_server.py ./index_template.html /opt/ethoscope_resources/

# Install any needed packages specified in requirements.txt
# Uncomment the following line if there is a requirements.txt in the repository
# RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir bottle

# Make port 8080 available to the world outside this container
EXPOSE 8080

# Change to the script's directory
# It is reccomended to mount this folder locally when running the container
WORKDIR /opt/ethoscope_resources

# Run pa_server.py when the container launches
CMD ["python", "pa_server.py", "--debug", "--port", "8080", "--log", "/opt/ethoscope_resources/contents/", "--static", "/opt/ethoscope_resources"]

# docker build -t ethoscope-resources . --no-cache
