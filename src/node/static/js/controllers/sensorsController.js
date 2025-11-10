(function() {
    var sensorsController = function($scope, $http) {
        $scope.csvFiles = [];
        $scope.selectedSensors = {};
        $scope.sensorData = {};
        $scope.showPressure = false; // Hidden by default

        // Default color palette for sensors
        var defaultColors = ['#FF6B6B', '#4ECDC4', '#45B7D1', '#FFA07A', '#98D8C8', '#F7DC6F', '#BB8FCE', '#85C1E9', '#F8C471', '#82E0AA'];
        var colorIndex = 0;

        // Load the list of CSV files and initialize sensor selection objects
        $http.get('/list_sensor_csv_files')
            .then(function(response) {
                var data = response.data;
                $scope.csvFiles = data.files.map(function(file) {
                    return file.replace('.csv', '');
                });

                // Initialize selectedSensors object with default colors
                $scope.csvFiles.forEach(function(file) {
                    $scope.selectedSensors[file] = {
                        selected: false,
                        color: defaultColors[colorIndex % defaultColors.length],
                        data: null,
                        loading: false
                    };
                    colorIndex++;
                });

                // Auto-select the default file with "room" in its name
                var defaultFile = $scope.csvFiles.find(file => file.toLowerCase().includes('room'));
                if (defaultFile) {
                    $scope.selectedSensors[defaultFile].selected = true;
                    $scope.fetchSensorData(defaultFile);
                }
            })
            .catch(function(error) {
                console.error("Error fetching CSV file list:", error);
            });

        // Fetch data for a specific sensor
        $scope.fetchSensorData = function(filename) {
            if (!filename || $scope.selectedSensors[filename].loading) {
                return;
            }

            $scope.selectedSensors[filename].loading = true;

            $http.get('/get_sensor_csv_data/' + filename + '.csv')
                .then(function(response) {
                    var data = response.data;
                    $scope.selectedSensors[filename].data = {
                        headers: data.headers,
                        rows: data.data
                    };
                    $scope.selectedSensors[filename].loading = false;
                    // Trigger a plot update after data is loaded
                    $scope.plotSelectedSensors();
                })
                .catch(function(error) {
                    console.error("Error fetching CSV data for " + filename + ":", error);
                    $scope.selectedSensors[filename].loading = false;
                });
        };

        // Plot only sensors that have data loaded
        $scope.plotSelectedSensors = function() {
            var selectedFiles = Object.keys($scope.selectedSensors).filter(function(file) {
                return $scope.selectedSensors[file].selected;
            });

            var sensorsWithData = selectedFiles.filter(function(file) {
                return $scope.selectedSensors[file].data;
            });

            if (sensorsWithData.length > 0) {
                plotMultiSensorData(sensorsWithData);
            } else if (selectedFiles.length === 0) {
                // Clear plot if no sensors selected
                document.getElementById('plotContainer').innerHTML = '';
            }
        };

        // Update plot when sensor selection changes
        $scope.updatePlot = function() {
            var selectedFiles = Object.keys($scope.selectedSensors).filter(function(file) {
                return $scope.selectedSensors[file].selected;
            });

            // Fetch data for newly selected sensors
            selectedFiles.forEach(function(file) {
                if (!$scope.selectedSensors[file].data && !$scope.selectedSensors[file].loading) {
                    $scope.fetchSensorData(file);
                }
            });

            // Plot sensors that already have data
            $scope.plotSelectedSensors();
        };

        // Helper functions for UI controls
        $scope.clearAllSensors = function() {
            $scope.csvFiles.forEach(function(file) {
                $scope.selectedSensors[file].selected = false;
            });
            $scope.updatePlot();
        };

        $scope.getSelectedCount = function() {
            return Object.keys($scope.selectedSensors).filter(function(file) {
                return $scope.selectedSensors[file].selected;
            }).length;
        };

        // Function to plot multiple sensor data using Plotly with shared x-axis
        function plotMultiSensorData(sensorFiles) {
            var traces = [];
            var allDates = [];

            // Process data for each selected sensor
            sensorFiles.forEach(function(filename) {
                var sensorInfo = $scope.selectedSensors[filename];
                if (!sensorInfo || !sensorInfo.data || !sensorInfo.data.rows) {
                    console.warn('Invalid sensor data for', filename);
                    return;
                }

                var data = sensorInfo.data.rows;
                var color = sensorInfo.color;

                var dates = [], temperature = [], humidity = [], pressure = [], light = [];

                // Limit the number of data points to prevent performance issues
                var maxDataPoints = 10000;
                var dataToProcess = data.length > maxDataPoints ?
                    data.slice(-maxDataPoints) : data;

                dataToProcess.forEach(function(row) {
                    // Skip header rows and metadata (lines starting with # or containing column names)
                    if (row && row[0] && !row[0].toString().startsWith('#') &&
                        row[0] !== 'Temperature' &&
                        row.length >= 5 &&
                        !isNaN(Date.parse(row[0]))) {

                        try {
                            var date = new Date(row[0]);
                            if (date && !isNaN(date.getTime())) {
                                dates.push(date);
                                allDates.push(date);
                                temperature.push(parseFloat(row[1]) || null);
                                humidity.push(parseFloat(row[2]) || null);
                                pressure.push(parseFloat(row[3]) || null);
                                light.push(parseFloat(row[4]) || null);
                            }
                        } catch (e) {
                            // Skip invalid date entries
                            console.warn('Invalid date in row:', row[0]);
                        }
                    }
                });

                // Only create traces if we have valid data
                if (dates.length > 0) {
                    // Create traces for each sensor type with the sensor's color
                    traces.push(
                        {
                            x: dates,
                            y: temperature,
                            type: 'scatter',
                            mode: 'lines',
                            name: filename + ' - Temperature',
                            line: { color: color, width: 2 },
                            yaxis: 'y1',
                            xaxis: 'x',
                            hovertemplate: '<b>' + filename + '</b><br>Temperature: %{y:.1f}°C<br>%{x}<extra></extra>'
                        },
                        {
                            x: dates,
                            y: humidity,
                            type: 'scatter',
                            mode: 'lines',
                            name: filename + ' - Humidity',
                            line: { color: color, width: 2, dash: 'dot' },
                            yaxis: 'y2',
                            xaxis: 'x',
                            hovertemplate: '<b>' + filename + '</b><br>Humidity: %{y:.1f}%<br>%{x}<extra></extra>'
                        }
                    );

                    // Add pressure trace only if enabled
                    if ($scope.showPressure) {
                        traces.push({
                            x: dates,
                            y: pressure,
                            type: 'scatter',
                            mode: 'lines',
                            name: filename + ' - Pressure',
                            line: { color: color, width: 2, dash: 'dash' },
                            yaxis: 'y3',
                            xaxis: 'x',
                            hovertemplate: '<b>' + filename + '</b><br>Pressure: %{y:.1f} hPa<br>%{x}<extra></extra>'
                        });
                    }

                    // Add light trace
                    traces.push({
                        x: dates,
                        y: light,
                        type: 'scatter',
                        mode: 'lines',
                        name: filename + ' - Light',
                        line: { color: color, width: 2, dash: 'dashdot' },
                        yaxis: $scope.showPressure ? 'y4' : 'y3',
                        xaxis: 'x',
                        hovertemplate: '<b>' + filename + '</b><br>Light: %{y:.1f} lux<br>%{x}<extra></extra>'
                    });
                }
            });

            // Calculate date range for display (last 7 days by default)
            var now = new Date();
            var sevenDaysAgo = new Date(now.getTime() - (7 * 24 * 60 * 60 * 1000));

            // Use reduce to find min/max dates to avoid stack overflow with large arrays
            var firstDate = sevenDaysAgo;
            var lastDate = now;

            if (allDates.length > 0) {
                firstDate = allDates.reduce(function(min, date) {
                    return date < min ? date : min;
                }, allDates[0]);

                lastDate = allDates.reduce(function(max, date) {
                    return date > max ? date : max;
                }, allDates[0]);
            }

            // Create legend annotations for each graph
            var annotations = [];

            // Build legend text for each graph
            var legendText = sensorFiles.map(function(filename) {
                var color = $scope.selectedSensors[filename].color;
                return '<span style="color:' + color + '; font-weight: bold;">● ' + filename + '</span>';
            }).join('  ');

            // Add legend annotations for each subplot
            annotations.push({
                text: legendText,
                xref: 'paper',
                yref: 'paper',
                x: 0.02,
                y: 0.98,
                xanchor: 'left',
                yanchor: 'top',
                showarrow: false,
                font: { size: 11 },
                bgcolor: 'rgba(255, 255, 255, 0.8)',
                bordercolor: '#ddd',
                borderwidth: 1
            });

            if ($scope.showPressure) {
                // Legend for Humidity (when pressure is shown)
                annotations.push({
                    text: legendText,
                    xref: 'paper',
                    yref: 'paper',
                    x: 0.02,
                    y: 0.68,
                    xanchor: 'left',
                    yanchor: 'top',
                    showarrow: false,
                    font: { size: 11 },
                    bgcolor: 'rgba(255, 255, 255, 0.8)',
                    bordercolor: '#ddd',
                    borderwidth: 1
                });

                // Legend for Pressure
                annotations.push({
                    text: legendText,
                    xref: 'paper',
                    yref: 'paper',
                    x: 0.02,
                    y: 0.43,
                    xanchor: 'left',
                    yanchor: 'top',
                    showarrow: false,
                    font: { size: 11 },
                    bgcolor: 'rgba(255, 255, 255, 0.8)',
                    bordercolor: '#ddd',
                    borderwidth: 1
                });

                // Legend for Light (when pressure is shown)
                annotations.push({
                    text: legendText,
                    xref: 'paper',
                    yref: 'paper',
                    x: 0.02,
                    y: 0.18,
                    xanchor: 'left',
                    yanchor: 'top',
                    showarrow: false,
                    font: { size: 11 },
                    bgcolor: 'rgba(255, 255, 255, 0.8)',
                    bordercolor: '#ddd',
                    borderwidth: 1
                });
            } else {
                // Legend for Humidity (when pressure is hidden)
                annotations.push({
                    text: legendText,
                    xref: 'paper',
                    yref: 'paper',
                    x: 0.02,
                    y: 0.60,
                    xanchor: 'left',
                    yanchor: 'top',
                    showarrow: false,
                    font: { size: 11 },
                    bgcolor: 'rgba(255, 255, 255, 0.8)',
                    bordercolor: '#ddd',
                    borderwidth: 1
                });

                // Legend for Light (when pressure is hidden)
                annotations.push({
                    text: legendText,
                    xref: 'paper',
                    yref: 'paper',
                    x: 0.02,
                    y: 0.26,
                    xanchor: 'left',
                    yanchor: 'top',
                    showarrow: false,
                    font: { size: 11 },
                    bgcolor: 'rgba(255, 255, 255, 0.8)',
                    bordercolor: '#ddd',
                    borderwidth: 1
                });
            }

            // Create layout with shared x-axis and multiple y-axes
            var layout = {
                height: $scope.showPressure ? 2000 : 1500,
                showlegend: false,
                title: {
                    text: 'Multi-Sensor Data Overview (' + sensorFiles.length + ' sensors)',
                    font: { size: 18 }
                },
                annotations: annotations,
                // Main x-axis (shared)
                xaxis: {
                    title: 'Date',
                    domain: [0, 1],
                    range: [sevenDaysAgo, lastDate],
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
                margin: {
                    t: 80,
                    b: 100,
                    l: 80,
                    r: 50
                }
            };

            // Dynamic y-axis configuration based on pressure visibility
            if ($scope.showPressure) {
                // 4 graphs: Temperature, Humidity, Pressure, Light
                layout.yaxis = {
                    title: 'Temperature (°C)',
                    domain: [0.75, 1],
                    titlefont: { color: '#333' },
                    tickfont: { color: '#333' }
                };
                layout.yaxis2 = {
                    title: 'Humidity (%)',
                    domain: [0.5, 0.7],
                    range: [20, 80],
                    titlefont: { color: '#333' },
                    tickfont: { color: '#333' }
                };
                layout.yaxis3 = {
                    title: 'Pressure (hPa)',
                    domain: [0.25, 0.45],
                    range: [980, 1050],
                    titlefont: { color: '#333' },
                    tickfont: { color: '#333' }
                };
                layout.yaxis4 = {
                    title: 'Light (lux)',
                    domain: [0, 0.2],
                    titlefont: { color: '#333' },
                    tickfont: { color: '#333' }
                };
            } else {
                // 3 graphs: Temperature, Humidity, Light
                layout.yaxis = {
                    title: 'Temperature (°C)',
                    domain: [0.67, 1],
                    titlefont: { color: '#333' },
                    tickfont: { color: '#333' }
                };
                layout.yaxis2 = {
                    title: 'Humidity (%)',
                    domain: [0.33, 0.62],
                    range: [20, 80],
                    titlefont: { color: '#333' },
                    tickfont: { color: '#333' }
                };
                layout.yaxis3 = {
                    title: 'Light (lux)',
                    domain: [0, 0.28],
                    titlefont: { color: '#333' },
                    tickfont: { color: '#333' }
                };
            }

            // Plot the unified chart with shared x-axis
            if (traces.length > 0) {
                Plotly.newPlot('plotContainer', traces, layout);
            } else {
                console.warn('No valid traces to plot');
                document.getElementById('plotContainer').innerHTML = '<div class="text-center text-muted p-4">No valid data to display</div>';
            }
        }
    };

    angular.module('flyApp').controller('sensorsController', sensorsController);
})();
