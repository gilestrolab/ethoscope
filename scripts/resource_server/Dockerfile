# Use an official Python runtime as a parent image
FROM python:3

# Clone the repository from GitHub
RUN apt-get update && \
    apt-get install -y git && \
    git clone https://github.com/gilestrolab/ethoscope.git /opt/ethoscope && \
    ln -s /opt/ethoscope/scripts/resource_server /opt/ethoscope_resources

# Change to the script's directory
# It is reccomended to mount this folder locally when running the container
WORKDIR /opt/ethoscope_resources

# Install any needed packages specified in requirements.txt
# Uncomment the following line if there is a requirements.txt in the repository
# RUN pip install --no-cache-dir -r requirements.txt

# Make port 8080 available to the world outside this container
EXPOSE 8080

# Run pa_server.py when the container launches
CMD ["python", "pa_server.py", "--debug", "--port", "8080", "--log", "/opt/ethoscope_resources/", "--static", "/opt/ethoscope_resources"]


# docker build -t ethoscope-resources .