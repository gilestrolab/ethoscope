(function() {
  var picker;

  picker = angular.module('daterangepicker', []);

  picker.constant('dateRangePickerConfig', {
    clearLabel: 'Clear',
    locale: {
      separator: ' - ',
      format: 'YYYY-MM-DD'
    }
  });

  picker.directive('dateRangePicker', ['$compile', '$timeout', '$parse', 'dateRangePickerConfig', function($compile, $timeout, $parse, dateRangePickerConfig) {
    return {
      require: 'ngModel',
      restrict: 'A',
      scope: {
        min: '=',
        max: '=',
        model: '=ngModel',
        opts: '=options',
        clearable: '='
      },
      link: function($scope, element, attrs, modelCtrl) {
        var _clear, _init, _initBoundaryField, _mergeOpts, _picker, _setDatePoint, _setEndDate, _setStartDate, _validate, _validateMax, _validateMin, customOpts, el, opts;
        _mergeOpts = function() {
          var extend, localeExtend;
          localeExtend = angular.extend.apply(angular, Array.prototype.slice.call(arguments).map(function(opt) {
            return opt != null ? opt.locale : void 0;
          }).filter(function(opt) {
            return !!opt;
          }));
          extend = angular.extend.apply(angular, arguments);
          extend.locale = localeExtend;
          return extend;
        };
        el = $(element);
        customOpts = $scope.opts;
        opts = _mergeOpts({}, dateRangePickerConfig, customOpts);
        _picker = null;
        _clear = function() {
          _picker.setStartDate();
          return _picker.setEndDate();
        };
        _setDatePoint = function(setter) {
          return function(newValue) {
            if (_picker && newValue && typeof moment !== 'undefined') {
              var momentObj = moment(newValue);
              if (momentObj.isValid()) {
                return setter(momentObj);
              } else {
                console.warn('Invalid date in _setDatePoint:', newValue);
              }
            }
          };
        };
        _setStartDate = _setDatePoint(function(m) {
          if (_picker.endDate < m) {
            _picker.setEndDate(m);
          }
          opts.startDate = m;
          return _picker.setStartDate(m);
        });
        _setEndDate = _setDatePoint(function(m) {
          if (_picker.startDate > m) {
            _picker.setStartDate(m);
          }
          opts.endDate = m;
          return _picker.setEndDate(m);
        });
        _validate = function(validator) {
          return function(boundary, actual) {
            if (boundary && actual && typeof moment !== 'undefined') {
              var boundaryMoment = moment(boundary);
              var actualMoment = moment(actual);
              if (boundaryMoment.isValid() && actualMoment.isValid()) {
                return validator(boundaryMoment, actualMoment);
              } else {
                console.warn('Invalid dates in _validate:', boundary, actual);
                return false;
              }
            } else {
              return true;
            }
          };
        };
        _validateMin = _validate(function(min, start) {
          return min.isBefore(start) || min.isSame(start, 'day');
        });
        _validateMax = _validate(function(max, end) {
          return max.isAfter(end) || max.isSame(end, 'day');
        });
        //The formatter has been modified from original version 
        //to provide a "formatted" field - this makes things easier to handle
        modelCtrl.$formatters.push(function(objValue) {
          var f;
          f = function(date) {
            // Check if moment.js is available and date is valid
            if (typeof moment === 'undefined') {
              console.warn('Moment.js not available in daterangepicker formatter');
              return '';
            }
            
            // Handle null/undefined dates
            if (date === null || date === undefined) {
              return '';
            }
            
            var momentObj;
            if (!moment.isMoment(date)) {
              momentObj = moment(date);
            } else {
              momentObj = date;
            }
            
            // Validate the moment object before formatting
            if (!momentObj.isValid()) {
              console.warn('Invalid date in daterangepicker formatter:', date);
              return '';
            }
            
            return momentObj.format(opts.locale.format);
          };
          
          if (opts.singleDatePicker && objValue) {
            return f(objValue);
          } else if (objValue && objValue.startDate) {
            var startFormatted = f(objValue.startDate);
            var endFormatted = f(objValue.endDate);
            
            // Only format if both dates are valid
            if (startFormatted && endFormatted) {
              if (modelCtrl.$viewValue && modelCtrl.$viewValue.length > 0) { 
                  objValue.formatted = modelCtrl.$viewValue + ", " + [startFormatted, endFormatted].join(opts.locale.separator);
              } else {
                  objValue.formatted = [startFormatted, endFormatted].join(opts.locale.separator);
              }
              return objValue.formatted;
            }
          }
          return '';
        });

        el.bind('blur', function() {
            if (modelCtrl.$modelValue) {
                modelCtrl.$modelValue.formatted = modelCtrl.$viewValue;
            }
        });
        
        modelCtrl.$render = function() {
          if (modelCtrl.$modelValue && modelCtrl.$modelValue.startDate) {
            _setStartDate(modelCtrl.$modelValue.startDate);
            _setEndDate(modelCtrl.$modelValue.endDate);
          } else {
            _clear();
          }
          return el.val(modelCtrl.$viewValue);
        };
        
        modelCtrl.$parsers.push(function(val) {
          var f, objValue, x;
          f = function(value) {
            if (typeof moment === 'undefined') {
              console.warn('Moment.js not available in daterangepicker parser');
              return null;
            }
            var momentObj = moment(value, opts.locale.format);
            return momentObj.isValid() ? momentObj : null;
          };
          objValue = {
            startDate: null,
            endDate: null
          };
          if (angular.isString(val) && val.length > 0) {
            if (opts.singleDatePicker) {
              objValue = f(val);
            } else {
              x = val.split(opts.locale.separator).map(f);
              // Only set if both dates are valid
              if (x[0] && x[1]) {
                objValue.startDate = x[0];
                objValue.endDate = x[1];
              }
            }
          }
          return objValue;
        });
        
        modelCtrl.$isEmpty = function(val) {
          return !(angular.isString(val) && val.length > 0);
        };
        _init = function() {
          // Check if required dependencies are available
          if (typeof moment === 'undefined') {
            console.warn('Moment.js not available for daterangepicker initialization, retrying...');
            $timeout(_init, 100);
            return;
          }
          
          if (typeof $.fn.daterangepicker === 'undefined') {
            console.warn('Daterangepicker not available, retrying...');
            $timeout(_init, 100);
            return;
          }
          
          var eventType, results;
          el.daterangepicker(angular.extend(opts, {
            autoUpdateInput: false
          }), function(start, end) {
            return $scope.$apply(function() {
              return $scope.model = opts.singleDatePicker ? start : {
                startDate: start,
                endDate: end
              };
            });
          });
          _picker = el.data('daterangepicker');
          results = [];
          for (eventType in opts.eventHandlers) {
            results.push(el.on(eventType, function(e) {
              var eventName;
              eventName = e.type + '.' + e.namespace;
              return $scope.$evalAsync(opts.eventHandlers[eventName]);
            }));
          }
          return results;
        };
        
        // Use $timeout to defer initialization until next digest cycle
        $timeout(_init, 0);
        $scope.$watch('model.startDate', function(n) {
          return _setStartDate(n);
        });
        $scope.$watch('model.endDate', function(n) {
          return _setEndDate(n);
        });
        _initBoundaryField = function(field, validator, modelField, optName) {
          if (attrs[field]) {
            modelCtrl.$validators[field] = function(value) {
              return value && validator(opts[optName], value[modelField]);
            };
            return $scope.$watch(field, function(date) {
              opts[optName] = date ? moment(date) : false;
              return _init();
            });
          }
        };
        _initBoundaryField('min', _validateMin, 'startDate', 'minDate');
        _initBoundaryField('max', _validateMax, 'endDate', 'maxDate');
        if (attrs.options) {
          $scope.$watch('opts', function(newOpts) {
            opts = _mergeOpts(opts, newOpts);
            return _init();
          }, true);
        }
        if (attrs.clearable) {
          $scope.$watch('clearable', function(newClearable) {
            if (newClearable) {
              opts = _mergeOpts(opts, {
                locale: {
                  cancelLabel: opts.clearLabel
                }
              });
            }
            _init();
            if (newClearable) {
              return el.on('cancel.daterangepicker', function() {
                return $scope.$apply(function() {
                  return $scope.model = opts.singleDatePicker ? null : {
                    startDate: null,
                    endDate: null
                  };
                });
              });
            }
          });
        }
        return $scope.$on('$destroy', function() {
          return _picker != null ? _picker.remove() : void 0;
        });
      }
    };
  }]);


}).call(this);
