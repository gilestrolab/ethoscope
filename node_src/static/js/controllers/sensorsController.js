(function() {
    var sensorsController = function($scope, $http) {
        $scope.csvFiles = [];
        $scope.selectedFile = null;
        $scope.headers = [];
        $scope.data = [];

        // Load the list of CSV files and remove `.csv` extension before assigning to scope
        $http.get('/list_sensor_csv_files')
            .success(function(response) {
                $scope.csvFiles = response.files.map(function(file) {
                    return file.replace('.csv', '');
                });

                // Find and select the default file with "room" in its name
                var defaultFileIndex = $scope.csvFiles.findIndex(file => file.toLowerCase().includes('room'));
                if (defaultFileIndex !== -1) {
                    $scope.selectedFile = $scope.csvFiles[defaultFileIndex];
                    // Automatically fetch data for the default selected file
                    $scope.fetchAndPlotData();
                }
            })
            .error(function(error) {
                console.error("Error fetching CSV file list:", error);
            });

        // Fetch and plot data when a file is selected
        $scope.fetchAndPlotData = function() {
            if ($scope.selectedFile) {
                // When fetching data, remember to add `.csv` back to the file name
                $http.get('/get_sensor_csv_data/' + $scope.selectedFile + '.csv')
                    .success(function(response) {
                        $scope.headers = response.headers;
                        $scope.data = response.data;
                        plotSensorData($scope.headers, $scope.data);
                    })
                    .error(function(error) {
                        console.error("Error fetching CSV data:", error);
                    });
            }
        };


        // Function to plot the sensor data using Plotly
        function plotSensorData(headers, data) {
            var dates = [],
                temperature = [],
                humidity = [],
                pressure = [],
                light = [];
            data.forEach(function(row) {
                dates.push(new Date(row[0]));
                temperature.push(parseFloat(row[1]));
                humidity.push(parseFloat(row[2]));
                pressure.push(parseFloat(row[3]));
                light.push(parseFloat(row[4]));
            });

            // Layout configuration function
            var layout = function(title, yRange = null) {
                return {
                    title: title,
                    xaxis: {
                        title: 'Date'
                    },
                    yaxis: {
                        title: 'Value',
                        range: yRange
                    },
                    margin: {
                        t: 50
                    },
                    autosize: true,
                    //width: 700,
                    //height: 400
                };
            };

            // Plot each sensor data in its respective div with specified colors
            Plotly.newPlot('plotTemperature', [{
                x: dates,
                y: temperature,
                mode: 'lines',
                name: 'Temperature',
                line: {
                    color: 'red'
                }
            }], layout('Temperature', [10, 35]));
            Plotly.newPlot('plotHumidity', [{
                x: dates,
                y: humidity,
                mode: 'lines',
                name: 'Humidity'
            }], layout('Humidity', [20, 80]));
            Plotly.newPlot('plotPressure', [{
                x: dates,
                y: pressure,
                mode: 'lines',
                name: 'Pressure'
            }], layout('Pressure', [980, 1050]));
            Plotly.newPlot('plotLight', [{
                x: dates,
                y: light,
                mode: 'lines',
                name: 'Light',
                line: {
                    color: 'orange'
                }
            }], layout('Light'));
        }
    };

    angular.module('flyApp').controller('sensorsController', sensorsController);
})();