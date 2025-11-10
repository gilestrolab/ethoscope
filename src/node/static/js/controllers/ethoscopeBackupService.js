(function() {
    'use strict';

    var app = angular.module('flyApp');

    app.factory('ethoscopeBackupService', function($http) {
        return {

            /**
             * Load backup information from the device-specific endpoint
             */
            loadBackupInfo: function(device_id, $scope, forceLoad) {
                // Throttle backup info requests to maximum once every 10 seconds (unless forced)
                var now = Date.now();
                if (!forceLoad && now - $scope.lastBackupStatusLoad < 10000) {
                    return;
                }
                $scope.lastBackupStatusLoad = now;

                // Use device-specific backup endpoint (GET request)
                return $http.get('/device/' + device_id + '/backup', {
                        timeout: 5000
                    })
                    .then(function(response) {
                        var backupData = response.data;
                        console.log('DEBUG: Received backup data from endpoint:', backupData);

                        // Store backup info directly - the endpoint returns the complete backup status
                        $scope.device.backup_info = backupData;

                        // Transform the data to match the expected frontend structure
                        if (backupData.backup_status) {
                            // Deep copy the backup_status to avoid modifying the original
                            var backupTypes = JSON.parse(JSON.stringify(backupData.backup_status));

                            // Enhance MySQL backup status with last_backup date from MariaDB data
                            if (backupTypes.mysql && backupTypes.mysql.available &&
                                backupData.databases && backupData.databases.MariaDB) {

                                // Find the most recent MariaDB database date
                                var latestDate = 0;
                                for (var dbName in backupData.databases.MariaDB) {
                                    if (backupData.databases.MariaDB.hasOwnProperty(dbName)) {
                                        var dbInfo = backupData.databases.MariaDB[dbName];
                                        if (dbInfo.date && dbInfo.date > latestDate) {
                                            latestDate = dbInfo.date;
                                        }
                                    }
                                }

                                if (latestDate > 0) {
                                    backupTypes.mysql.last_backup = latestDate;

                                    // Also add size information from MariaDB data
                                    var totalSize = 0;
                                    for (var dbName in backupData.databases.MariaDB) {
                                        if (backupData.databases.MariaDB.hasOwnProperty(dbName)) {
                                            var dbInfo = backupData.databases.MariaDB[dbName];
                                            if (dbInfo.db_size_bytes) {
                                                totalSize += dbInfo.db_size_bytes;
                                            }
                                        }
                                    }
                                    backupTypes.mysql.size = totalSize;

                                    console.log('DEBUG: Enhanced MySQL backup status - last_backup:', latestDate, 'size:', totalSize);
                                }
                            }

                            $scope.device.backup_status_detailed = {
                                backup_types: backupTypes,
                                individual_files: {}
                            };

                            // Transform SQLite individual files data
                            if (backupData.databases && backupData.databases.SQLite) {
                                var sqliteFiles = [];

                                // Local utility function for file size formatting
                                function formatBytes(bytes) {
                                    if (!bytes || bytes === 0) return '0 B';
                                    const k = 1024;
                                    const sizes = ['B', 'KB', 'MB', 'GB'];
                                    const i = Math.floor(Math.log(bytes) / Math.log(k));
                                    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
                                }

                                for (var fileName in backupData.databases.SQLite) {
                                    if (backupData.databases.SQLite.hasOwnProperty(fileName)) {
                                        var fileInfo = backupData.databases.SQLite[fileName];

                                        // Check for enhanced data sources
                                        var isRsyncEnhanced = fileInfo.rsync_enhanced || false;
                                        var isFilesystemEnhanced = fileInfo.filesystem_enhanced || false;
                                        var enhancementSource = '';

                                        if (isRsyncEnhanced) {
                                            enhancementSource = 'rsync';
                                        } else if (isFilesystemEnhanced) {
                                            enhancementSource = 'filesystem';
                                        }

                                        // Use enhanced size_human if available, otherwise format filesize
                                        var sizeHuman = fileInfo.size_human || formatBytes(fileInfo.filesize || 0);

                                        sqliteFiles.push({
                                            name: fileName,
                                            modified: fileInfo.date || 0,
                                            size_human: sizeHuman,
                                            size_bytes: fileInfo.filesize || 0,
                                            status: fileInfo.file_exists ? 'backed-up' : 'missing',
                                            path: fileInfo.path || '',
                                            db_status: fileInfo.db_status || 'unknown',
                                            enhancement_source: enhancementSource,
                                            is_enhanced: isRsyncEnhanced || isFilesystemEnhanced
                                        });
                                    }
                                }

                                $scope.device.backup_status_detailed.individual_files.sqlite = {
                                    files: sqliteFiles
                                };

                                console.log('DEBUG: Created individual SQLite files structure:', sqliteFiles.length, 'files');
                            }

                            // Process video files if available from enhanced rsync data
                            if (backupData.video_files || (backupData.backup_status && backupData.backup_status.video) ||
                                (backupData.databases && backupData.databases.Video)) {

                                var videoFileArray = [];

                                // Process video data from databases.Video structure (preferred method)
                                if (backupData.databases && backupData.databases.Video && backupData.databases.Video.video_backup) {
                                    var videoBackup = backupData.databases.Video.video_backup;
                                    var videoFiles = videoBackup.files || {};

                                    for (var filename in videoFiles) {
                                        if (videoFiles.hasOwnProperty(filename)) {
                                            var fileInfo = videoFiles[filename];

                                            // Check enhancement source
                                            var isRsyncEnhanced = fileInfo.rsync_enhanced || false;
                                            var isFilesystemEnhanced = fileInfo.filesystem_enhanced || false;
                                            var enhancementSource = '';

                                            if (isRsyncEnhanced) {
                                                enhancementSource = 'rsync';
                                            } else if (isFilesystemEnhanced) {
                                                enhancementSource = 'filesystem';
                                            }

                                            function formatBytes(bytes) {
                                                if (!bytes || bytes === 0) return '0 B';
                                                const k = 1024;
                                                const sizes = ['B', 'KB', 'MB', 'GB'];
                                                const i = Math.floor(Math.log(bytes) / Math.log(k));
                                                return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
                                            }

                                            videoFileArray.push({
                                                name: filename,
                                                size_bytes: fileInfo.size_bytes || 0,
                                                size_human: fileInfo.size_human || formatBytes(fileInfo.size_bytes || 0),
                                                is_h264: filename.endsWith('.h264'),
                                                path: fileInfo.path || '',
                                                enhancement_source: enhancementSource,
                                                is_enhanced: isRsyncEnhanced || isFilesystemEnhanced
                                            });
                                        }
                                    }

                                    console.log('DEBUG: Processed video data from databases.Video:', videoFileArray.length, 'files');
                                }

                                $scope.device.backup_status_detailed.individual_files.videos = {
                                    files: videoFileArray
                                };

                                // If no video data in databases.Video, fall back to enhanced rsync status
                                if (videoFileArray.length === 0) {
                                    // loadEnhancedVideoInfo() - would need to be implemented if needed
                                }
                            }

                            // Also preserve the legacy databases structure for MariaDB (since it's not in individual_files yet)
                            if (backupData.databases) {
                                $scope.device.databases = backupData.databases;
                            }
                        }

                        // Update backup summary
                        this.updateBackupSummary($scope);
                        return response;
                    }.bind(this))
                    .catch(function(error) {
                        console.error('Failed to load backup info:', error);
                        // Don't overwrite existing backup info on error - just log the error
                        // This prevents backup visualization from disappearing if there's a temporary network issue
                        if (!$scope.device.backup_info && !$scope.device.backup_status_detailed) {
                            // Only set empty backup info if we have no backup data at all
                            $scope.device.backup_info = {
                                backup_status: {
                                    mysql: {
                                        available: false,
                                        database_count: 0,
                                        databases: []
                                    },
                                    sqlite: {
                                        available: false,
                                        database_count: 0,
                                        databases: []
                                    },
                                    total_databases: 0
                                },
                                recommended_backup_type: null
                            };
                            this.updateBackupSummary($scope);
                        }
                        throw error;
                    }.bind(this));
            },

            /**
             * Update backup summary cache - called when device data changes
             */
            updateBackupSummary: function($scope) {
                // Use device backup info if available, otherwise fall back to legacy device.databases
                if ($scope.device && $scope.device.backup_info) {
                    this.updateBackupSummaryFromBackupInfo($scope);
                } else if ($scope.device && $scope.device.databases) {
                    this.updateBackupSummaryFromLegacyData($scope);
                } else {
                    $scope.backupSummary = null;
                }
            },

            /**
             * Update backup summary from device backup info endpoint
             */
            updateBackupSummaryFromBackupInfo: function($scope) {
                const backupStatus = $scope.device.backup_info.backup_status;
                if (!backupStatus) {
                    console.log('DEBUG: No backup_status found in backup_info');
                    $scope.backupSummary = null;
                    return;
                }

                let total = backupStatus.total_databases || 0;
                let backedUp = 0;
                let missing = 0;
                let processing = 0;

                // Count available backup types
                if (backupStatus.mysql && backupStatus.mysql.available) {
                    backedUp += backupStatus.mysql.database_count || 0;
                }
                if (backupStatus.sqlite && backupStatus.sqlite.available) {
                    backedUp += backupStatus.sqlite.database_count || 0;
                }

                // Calculate missing
                missing = total - backedUp;

                let overallStatus = 'Unknown';
                if (total === 0) {
                    overallStatus = 'No Databases';
                } else if (backedUp === total) {
                    overallStatus = 'All Backed Up';
                } else if (backedUp === 0) {
                    overallStatus = 'None Backed Up';
                } else {
                    overallStatus = 'Partial Backup';
                }

                console.log('DEBUG: Updated backup summary from backup info:', {
                    total: total,
                    backedUp: backedUp,
                    missing: missing,
                    overallStatus: overallStatus,
                    useDetailedStatus: true,
                    hasIndividualFiles: $scope.device.backup_status_detailed &&
                                       $scope.device.backup_status_detailed.individual_files &&
                                       $scope.device.backup_status_detailed.individual_files.sqlite
                });

                $scope.backupSummary = {
                    total: total,
                    backedUp: backedUp,
                    missing: missing,
                    processing: processing,
                    overallStatus: overallStatus,
                    useBackupInfo: true,
                    useDetailedStatus: true,
                    totalSize: 0 // Will be calculated if needed
                };
            },

            /**
             * Update backup summary from legacy device databases data (fallback)
             */
            updateBackupSummaryFromLegacyData: function($scope) {
                let total = 0;
                let backedUp = 0;
                let missing = 0;
                let processing = 0;

                // Count SQLite databases
                if ($scope.device.databases.SQLite) {
                    for (let dbName in $scope.device.databases.SQLite) {
                        if ($scope.device.databases.SQLite.hasOwnProperty(dbName)) {
                            total++;
                            const dbInfo = $scope.device.databases.SQLite[dbName];

                            if (dbInfo.file_exists === true) {
                                backedUp++;
                            } else if (dbInfo.file_exists === false) {
                                missing++;
                            } else if (dbInfo.db_status === 'tracking') {
                                processing++;
                            }
                        }
                    }
                }

                // Count MariaDB databases
                if ($scope.device.databases.MariaDB) {
                    for (let dbName in $scope.device.databases.MariaDB) {
                        if ($scope.device.databases.MariaDB.hasOwnProperty(dbName)) {
                            total++;
                            const dbInfo = $scope.device.databases.MariaDB[dbName];

                            if (dbInfo.file_exists === true) {
                                backedUp++;
                            } else if (dbInfo.file_exists === false) {
                                missing++;
                            } else if (dbInfo.db_status === 'tracking') {
                                processing++;
                            }
                        }
                    }
                }

                let overallStatus = 'Unknown';
                if (total === 0) {
                    overallStatus = 'No Databases';
                } else if (backedUp === total) {
                    overallStatus = 'All Backed Up';
                } else if (backedUp === 0) {
                    overallStatus = 'None Backed Up';
                } else {
                    overallStatus = 'Partial Backup';
                }

                $scope.backupSummary = {
                    total: total,
                    backedUp: backedUp,
                    missing: missing,
                    processing: processing,
                    overallStatus: overallStatus,
                    useDetailedStatus: false
                };
            }
        };
    });

})();
