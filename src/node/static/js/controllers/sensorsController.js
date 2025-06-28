(function() {
    var sensorsController = function($scope, $http) {
        $scope.csvFiles = [];
        $scope.selectedFile = null;
        $scope.headers = [];
        $scope.data = [];

        // Load the list of CSV files and remove `.csv` extension before assigning to scope
        $http.get('/list_sensor_csv_files')
            .then(function(response) { var data = response.data;
                $scope.csvFiles = data.files.map(function(file) {
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
            .catch(function(error) {
                console.error("Error fetching CSV file list:", error);
            });

        // Fetch and plot data when a file is selected
        $scope.fetchAndPlotData = function() {
            if ($scope.selectedFile) {
                // When fetching data, remember to add `.csv` back to the file name
                $http.get('/get_sensor_csv_data/' + $scope.selectedFile + '.csv')
                    .then(function(response) { var data = response.data;
                        $scope.headers = data.headers;
                        $scope.data = data.data;
                        plotSensorData($scope.headers, $scope.data);
                    })
                    .catch(function(error) {
                        console.error("Error fetching CSV data:", error);
                    });
            }
        };

        // Function to plot the sensor data using Plotly with shared x-axis
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

            // Calculate date range for last 15 days
            var now = new Date();
            var fifteenDaysAgo = new Date(now.getTime() - (15 * 24 * 60 * 60 * 1000));
            var firstDate = dates.length > 0 ? dates[0] : fifteenDaysAgo;
            var lastDate = dates.length > 0 ? dates[dates.length - 1] : now;

            // Create data traces for all sensors
            var traces = [
                {
                    x: dates,
                    y: temperature,
                    type: 'scatter',
                    mode: 'lines',
                    name: 'Temperature',
                    line: { color: 'red' },
                    yaxis: 'y1',
                    xaxis: 'x'
                },
                {
                    x: dates,
                    y: humidity,
                    type: 'scatter',
                    mode: 'lines',
                    name: 'Humidity',
                    line: { color: 'blue' },
                    yaxis: 'y2',
                    xaxis: 'x'
                },
                {
                    x: dates,
                    y: pressure,
                    type: 'scatter',
                    mode: 'lines',
                    name: 'Pressure',
                    line: { color: 'green' },
                    yaxis: 'y3',
                    xaxis: 'x'
                },
                {
                    x: dates,
                    y: light,
                    type: 'scatter',
                    mode: 'lines',
                    name: 'Light',
                    line: { color: 'orange' },
                    yaxis: 'y4',
                    xaxis: 'x'
                }
            ];

            // Create layout with shared x-axis and multiple y-axes
            var layout = {
                height: 2000,
                showlegend: false,
                title: 'Sensor Data Overview',
                // Main x-axis (shared)
                xaxis: {
                    title: 'Date',
                    domain: [0, 1],
                    range: [fifteenDaysAgo, lastDate],
                    rangeslider: {
                        visible: true,
                        range: [firstDate, lastDate]
                    },
                    rangeselector: {
                        buttons: [
                            {
                                count: 1,
                                label: '1d',
                                step: 'day',
                                stepmode: 'backward'
                            },
                            {
                                count: 7,
                                label: '7d',
                                step: 'day',
                                stepmode: 'backward'
                            },
                            {
                                count: 15,
                                label: '15d',
                                step: 'day',
                                stepmode: 'backward'
                            },
                            {
                                count: 30,
                                label: '30d',
                                step: 'day',
                                stepmode: 'backward'
                            },
                            {
                                step: 'all',
                                label: 'All'
                            }
                        ]
                    }
                },
                // Y-axis for Temperature (top subplot)
                yaxis: {
                    title: 'Temperature (°C)',
                    domain: [0.75, 1],
                    range: [10, 35],
                    titlefont: { color: 'red' },
                    tickfont: { color: 'red' }
                },
                // Y-axis for Humidity (second subplot)
                yaxis2: {
                    title: 'Humidity (%)',
                    domain: [0.5, 0.7],
                    range: [20, 80],
                    titlefont: { color: 'blue' },
                    tickfont: { color: 'blue' }
                },
                // Y-axis for Pressure (third subplot)
                yaxis3: {
                    title: 'Pressure (hPa)',
                    domain: [0.25, 0.45],
                    range: [980, 1050],
                    titlefont: { color: 'green' },
                    tickfont: { color: 'green' }
                },
                // Y-axis for Light (bottom subplot)
                yaxis4: {
                    title: 'Light (lux)',
                    domain: [0, 0.2],
                    titlefont: { color: 'orange' },
                    tickfont: { color: 'orange' }
                },
                margin: {
                    t: 50,
                    b: 100,
                    l: 80,
                    r: 50
                }
            };

            // Plot the unified chart with shared x-axis
            Plotly.newPlot('plotContainer', traces, layout);
        }
    };

    angular.module('flyApp').controller('sensorsController', sensorsController);
})();