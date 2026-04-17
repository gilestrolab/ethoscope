(function(){
    var sensorsManagementController = function($scope, $http, $timeout){

        // Initialize scope variables
        $scope.sensors = {};
        $scope.incubators = {};
        $scope.selectedSensor = {};
        $scope.sensorToDelete = null;
        $scope.searchText = '';
        $scope.showAll = false;
        $scope.sortType = 'name';
        $scope.sortReverse = false;
        $scope.globalAlerts = {};

        // Chart state
        $scope.csvSensors = {};  // keyed by csv filename (no extension)
        $scope.showPressure = false;
        var defaultColors = ['#FF6B6B', '#4ECDC4', '#45B7D1', '#FFA07A', '#98D8C8', '#F7DC6F', '#BB8FCE', '#85C1E9', '#F8C471', '#82E0AA'];

        // ===========================
        // SENSOR TABLE MANAGEMENT
        // ===========================

        $scope.sensorFilter = function(sensors, searchText, showAll) {
            if (!sensors) return [];
            var filtered = [];
            for (var key in sensors) {
                var sensor = sensors[key];
                sensor.key = key;
                if (!showAll && sensor.active === false) continue;
                filtered.push(sensor);
            }
            if (searchText) {
                filtered = filtered.filter(function(sensor) {
                    var s = searchText.toLowerCase();
                    return (sensor.name && sensor.name.toLowerCase().indexOf(s) !== -1) ||
                           (sensor.location && sensor.location.toLowerCase().indexOf(s) !== -1) ||
                           (sensor.description && sensor.description.toLowerCase().indexOf(s) !== -1) ||
                           (sensor.ip && sensor.ip.toLowerCase().indexOf(s) !== -1);
                });
            }
            return filtered;
        };

        var loadSensors = function() {
            $http.get('/sensors/merged')
                .then(function(response) {
                    $scope.sensors = response.data;
                    for (var key in $scope.sensors) {
                        if ($scope.sensors[key].global_alerts) {
                            $scope.globalAlerts = $scope.sensors[key].global_alerts;
                            break;
                        }
                    }
                })
                .catch(function(error) {
                    console.error('Error loading sensors:', error);
                });
        };

        var loadIncubators = function() {
            $http.get('/node/incubators')
                .then(function(response) {
                    $scope.incubators = response.data;
                })
                .catch(function(error) {
                    console.error('Error loading incubators:', error);
                });
        };

        // Sensor explicitly declares no alerts (e.g. virtual weather sensor)
        $scope.hasNoAlerts = function(sensor) {
            return sensor.no_alerts === true;
        };

        $scope.getAlertDisplay = function(sensor) {
            if (sensor.alerts && sensor.alerts.enabled) {
                return sensor.alerts.min_threshold + ' - ' + sensor.alerts.max_threshold + '\u00B0C';
            }
            return 'Global';
        };

        $scope.getSourceClass = function(source) {
            if (source === 'discovered') return 'badge-success';
            if (source === 'configured') return 'badge-secondary';
            if (source === 'both') return 'badge-info';
            return 'badge-light';
        };

        $scope.getStatusIcon = function(sensor) {
            if (sensor.status === 'offline' || sensor.status === 'configured') return 'text-muted';
            return 'text-success';
        };

        $scope.clearSelectedSensor = function() {
            $scope.selectedSensor = {
                active: true, name: '', URL: '', location: '', description: '',
                alerts: { enabled: false, min_threshold: 18.0, max_threshold: 28.0 }
            };
        };

        $scope.editSensor = function(sensor) {
            $scope.selectedSensor = angular.copy(sensor);
            $scope.selectedSensor._editing = true;
            $scope.selectedSensor._originalName = sensor.name;
            if (!$scope.selectedSensor.alerts) {
                $scope.selectedSensor.alerts = { enabled: false, min_threshold: 18.0, max_threshold: 28.0 };
            }
        };

        $scope.saveSensor = function() {
            var data = $scope.selectedSensor;
            var payload = {
                name: data.name,
                URL: data.URL || '',
                location: data.location || '',
                description: data.description || '',
                active: !!data.active,
                alerts: {
                    enabled: !!(data.alerts && data.alerts.enabled),
                    min_threshold: parseFloat((data.alerts && data.alerts.min_threshold) || 18.0),
                    max_threshold: parseFloat((data.alerts && data.alerts.max_threshold) || 28.0)
                }
            };

            var onSuccess = function() {
                $('#sensorModal').modal('hide');
                loadSensors();
                $scope.clearSelectedSensor();
            };

            if (data._editing) {
                payload.original_name = data._originalName;
                $http.post('/setup/update-sensor', payload)
                    .then(function(response) {
                        if (response.data.result === 'success') {
                            if (data.source === 'discovered' || data.source === 'both') pushToDevice(data);
                            onSuccess();
                        } else {
                            alert('Error updating sensor: ' + (response.data.message || 'Unknown error'));
                        }
                    })
                    .catch(function(error) {
                        console.error('Error updating sensor:', error);
                        alert('Error updating sensor. Please try again.');
                    });
            } else {
                $http.post('/setup/add-sensor', payload)
                    .then(function(response) {
                        if (response.data.result === 'success') {
                            onSuccess();
                        } else {
                            alert('Error adding sensor: ' + (response.data.message || 'Unknown error'));
                        }
                    })
                    .catch(function(error) {
                        console.error('Error adding sensor:', error);
                        alert('Error adding sensor. Please try again.');
                    });
            }
        };

        function pushToDevice(sensor) {
            if (!sensor.id) return;
            $http.post('/sensor/set', {
                id: sensor.id, name: sensor.name, location: sensor.location || ''
            }).catch(function(error) {
                console.warn('Could not push settings to physical sensor:', error);
            });
        }

        $scope.confirmDeleteSensor = function(sensor) {
            $scope.sensorToDelete = sensor;
        };

        $scope.deleteSensor = function() {
            if (!$scope.sensorToDelete) return;
            $http.post('/setup/delete-sensor', { name: $scope.sensorToDelete.name })
                .then(function(response) {
                    if (response.data.result === 'success') {
                        $('#deleteSensorModal').modal('hide');
                        loadSensors();
                    } else {
                        alert('Error deleting sensor: ' + (response.data.message || 'Unknown error'));
                    }
                })
                .catch(function(error) {
                    console.error('Error deleting sensor:', error);
                    alert('Error deleting sensor. Please try again.');
                });
            $scope.sensorToDelete = null;
        };

        // ===========================
        // CHART / DATA VISUALIZATION
        // ===========================

        var loadCsvFiles = function() {
            $http.get('/list_sensor_csv_files')
                .then(function(response) {
                    var files = response.data.files || [];
                    var colorIndex = 0;
                    files.forEach(function(file) {
                        var name = file.replace('.csv', '');
                        $scope.csvSensors[name] = {
                            selected: false,
                            color: defaultColors[colorIndex % defaultColors.length],
                            data: null,
                            loading: false
                        };
                        colorIndex++;
                    });
                })
                .catch(function(error) {
                    console.error('Error loading CSV file list:', error);
                });
        };

        // Match a sensor row to its CSV key (by name)
        $scope.getCsvKeyForSensor = function(sensor) {
            if (!sensor || !sensor.name) return null;
            // CSV files use a safe version of sensor name - try exact match first
            if ($scope.csvSensors[sensor.name]) return sensor.name;
            // Try sanitized name (alphanumeric + _-)
            var safe = sensor.name.replace(/[^a-zA-Z0-9_-]/g, '');
            if ($scope.csvSensors[safe]) return safe;
            return null;
        };

        // Natural sort: "etho_sensor_2A" before "etho_sensor_10A"
        function naturalCompare(a, b) {
            var ax = [], bx = [];
            a.replace(/(\d+)|(\D+)/g, function(_, $1, $2) { ax.push([$1 || Infinity, $2 || '']); });
            b.replace(/(\d+)|(\D+)/g, function(_, $1, $2) { bx.push([$1 || Infinity, $2 || '']); });
            for (var i = 0; i < Math.max(ax.length, bx.length); i++) {
                var ai = ax[i] || [Infinity, ''], bi = bx[i] || [Infinity, ''];
                var numA = Number(ai[0]), numB = Number(bi[0]);
                if (numA !== numB) return numA - numB;
                if (ai[1] < bi[1]) return -1;
                if (ai[1] > bi[1]) return 1;
            }
            return 0;
        }

        // Get CSV files that don't match any sensor in the table
        $scope.getUnmatchedCsvKeys = function() {
            var matched = {};
            for (var key in $scope.sensors) {
                var csvKey = $scope.getCsvKeyForSensor($scope.sensors[key]);
                if (csvKey) matched[csvKey] = true;
            }
            var unmatched = [];
            for (var file in $scope.csvSensors) {
                if (!matched[file]) unmatched.push(file);
            }
            return unmatched.sort(naturalCompare);
        };

        $scope.hasCsvFiles = function() {
            return Object.keys($scope.csvSensors).length > 0;
        };

        $scope.updatePlot = function() {
            var selectedFiles = [];
            for (var file in $scope.csvSensors) {
                if ($scope.csvSensors[file].selected) {
                    selectedFiles.push(file);
                    if (!$scope.csvSensors[file].data && !$scope.csvSensors[file].loading) {
                        fetchSensorData(file);
                    }
                }
            }
            plotSelectedSensors();
        };

        function fetchSensorData(filename) {
            if (!filename || $scope.csvSensors[filename].loading) return;
            $scope.csvSensors[filename].loading = true;
            $http.get('/get_sensor_csv_data/' + filename + '.csv')
                .then(function(response) {
                    $scope.csvSensors[filename].data = {
                        headers: response.data.headers,
                        rows: response.data.data
                    };
                    $scope.csvSensors[filename].loading = false;
                    plotSelectedSensors();
                })
                .catch(function(error) {
                    console.error('Error fetching CSV data for ' + filename + ':', error);
                    $scope.csvSensors[filename].loading = false;
                });
        }

        function plotSelectedSensors() {
            var sensorsWithData = [];
            for (var file in $scope.csvSensors) {
                if ($scope.csvSensors[file].selected && $scope.csvSensors[file].data) {
                    sensorsWithData.push(file);
                }
            }
            var container = document.getElementById('plotContainer');
            if (!container) return;
            if (sensorsWithData.length > 0) {
                plotMultiSensorData(sensorsWithData);
            } else {
                container.innerHTML = '';
            }
        }

        $scope.clearAllPlots = function() {
            for (var file in $scope.csvSensors) {
                $scope.csvSensors[file].selected = false;
            }
            $scope.updatePlot();
        };

        $scope.getPlotCount = function() {
            var count = 0;
            for (var file in $scope.csvSensors) {
                if ($scope.csvSensors[file].selected) count++;
            }
            return count;
        };

        // Plotly multi-sensor chart rendering
        function plotMultiSensorData(sensorFiles) {
            var traces = [];
            var allDates = [];

            sensorFiles.forEach(function(filename) {
                var sensorInfo = $scope.csvSensors[filename];
                if (!sensorInfo || !sensorInfo.data || !sensorInfo.data.rows) return;

                var data = sensorInfo.data.rows;
                var color = sensorInfo.color;
                var dates = [], temperature = [], humidity = [], pressure = [], light = [];

                var maxDataPoints = 10000;
                var dataToProcess = data.length > maxDataPoints ? data.slice(-maxDataPoints) : data;

                dataToProcess.forEach(function(row) {
                    if (row && row[0] && row[0].toString().charAt(0) !== '#' &&
                        row[0] !== 'Temperature' && row.length >= 5 &&
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
                        } catch (e) {}
                    }
                });

                if (dates.length > 0) {
                    traces.push(
                        {
                            x: dates, y: temperature, type: 'scatter', mode: 'lines',
                            name: filename + ' - Temperature',
                            line: { color: color, width: 2 }, yaxis: 'y1', xaxis: 'x',
                            hovertemplate: '<b>' + filename + '</b><br>Temperature: %{y:.1f}\u00B0C<br>%{x}<extra></extra>'
                        },
                        {
                            x: dates, y: humidity, type: 'scatter', mode: 'lines',
                            name: filename + ' - Humidity',
                            line: { color: color, width: 2, dash: 'dot' }, yaxis: 'y2', xaxis: 'x',
                            hovertemplate: '<b>' + filename + '</b><br>Humidity: %{y:.1f}%<br>%{x}<extra></extra>'
                        }
                    );

                    if ($scope.showPressure) {
                        traces.push({
                            x: dates, y: pressure, type: 'scatter', mode: 'lines',
                            name: filename + ' - Pressure',
                            line: { color: color, width: 2, dash: 'dash' }, yaxis: 'y3', xaxis: 'x',
                            hovertemplate: '<b>' + filename + '</b><br>Pressure: %{y:.1f} hPa<br>%{x}<extra></extra>'
                        });
                    }

                    traces.push({
                        x: dates, y: light, type: 'scatter', mode: 'lines',
                        name: filename + ' - Light',
                        line: { color: color, width: 2, dash: 'dashdot' },
                        yaxis: $scope.showPressure ? 'y4' : 'y3', xaxis: 'x',
                        hovertemplate: '<b>' + filename + '</b><br>Light: %{y:.1f} lux<br>%{x}<extra></extra>'
                    });
                }
            });

            var now = new Date();
            var sevenDaysAgo = new Date(now.getTime() - (7 * 24 * 60 * 60 * 1000));
            var lastDate = now;

            if (allDates.length > 0) {
                lastDate = allDates.reduce(function(max, d) { return d > max ? d : max; }, allDates[0]);
            }

            var legendText = sensorFiles.map(function(filename) {
                var color = $scope.csvSensors[filename].color;
                return '<span style="color:' + color + '; font-weight: bold;">\u25CF ' + filename + '</span>';
            }).join('  ');

            var annotations = [];
            annotations.push({
                text: legendText, xref: 'paper', yref: 'paper',
                x: 0.02, y: 0.98, xanchor: 'left', yanchor: 'top', showarrow: false,
                font: { size: 11 }, bgcolor: 'rgba(255,255,255,0.8)', bordercolor: '#ddd', borderwidth: 1
            });

            if ($scope.showPressure) {
                [0.68, 0.43, 0.18].forEach(function(yPos) {
                    annotations.push({
                        text: legendText, xref: 'paper', yref: 'paper',
                        x: 0.02, y: yPos, xanchor: 'left', yanchor: 'top', showarrow: false,
                        font: { size: 11 }, bgcolor: 'rgba(255,255,255,0.8)', bordercolor: '#ddd', borderwidth: 1
                    });
                });
            } else {
                [0.60, 0.26].forEach(function(yPos) {
                    annotations.push({
                        text: legendText, xref: 'paper', yref: 'paper',
                        x: 0.02, y: yPos, xanchor: 'left', yanchor: 'top', showarrow: false,
                        font: { size: 11 }, bgcolor: 'rgba(255,255,255,0.8)', bordercolor: '#ddd', borderwidth: 1
                    });
                });
            }

            var layout = {
                height: $scope.showPressure ? 2000 : 1500,
                showlegend: false,
                title: { text: 'Sensor Data (' + sensorFiles.length + ' sensors)', font: { size: 18 } },
                annotations: annotations,
                xaxis: {
                    title: 'Date', domain: [0, 1],
                    range: [sevenDaysAgo, lastDate],
                    rangeselector: {
                        buttons: [
                            { count: 1, label: '1d', step: 'day', stepmode: 'backward' },
                            { count: 7, label: '7d', step: 'day', stepmode: 'backward' },
                            { count: 15, label: '15d', step: 'day', stepmode: 'backward' },
                            { count: 30, label: '30d', step: 'day', stepmode: 'backward' },
                            { step: 'all', label: 'All' }
                        ]
                    }
                },
                margin: { t: 80, b: 100, l: 80, r: 50 }
            };

            if ($scope.showPressure) {
                layout.yaxis  = { title: 'Temperature (\u00B0C)', domain: [0.75, 1] };
                layout.yaxis2 = { title: 'Humidity (%)', domain: [0.5, 0.7], range: [20, 80] };
                layout.yaxis3 = { title: 'Pressure (hPa)', domain: [0.25, 0.45], range: [980, 1050] };
                layout.yaxis4 = { title: 'Light (lux)', domain: [0, 0.2] };
            } else {
                layout.yaxis  = { title: 'Temperature (\u00B0C)', domain: [0.67, 1] };
                layout.yaxis2 = { title: 'Humidity (%)', domain: [0.33, 0.62], range: [20, 80] };
                layout.yaxis3 = { title: 'Light (lux)', domain: [0, 0.28] };
            }

            if (traces.length > 0) {
                Plotly.newPlot('plotContainer', traces, layout);
            } else {
                document.getElementById('plotContainer').innerHTML =
                    '<div class="text-center text-muted p-4">No valid data to display</div>';
            }
        }

        // ===========================
        // INITIALIZATION
        // ===========================

        loadSensors();
        loadIncubators();
        loadCsvFiles();
    };

    angular.module('flyApp').controller('sensorsManagementController', sensorsManagementController);
}());
