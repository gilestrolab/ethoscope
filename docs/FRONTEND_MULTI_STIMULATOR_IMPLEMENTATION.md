# Frontend Multi-Stimulator Implementation

## Overview

This document summarizes the frontend implementation of the multi-stimulator feature, which allows users to configure multiple stimulators with individual date/time ranges through the web interface.

## Changes Made

### 1. HTML Template Updates (`src/node/static/pages/ethoscope.html`)

#### Key Modifications:
- **Replaced radio buttons with dropdown**: The interactor selection now uses a dropdown menu instead of radio buttons for better scalability
- **Added multi-stimulator configuration interface**: New UI section that appears when MultiStimulator is selected
- **Preserved backward compatibility**: Single stimulator configuration continues to work as before

#### New UI Components:
1. **Stimulator Type Dropdown**: Clean dropdown selection for choosing stimulator type
2. **Multi-Stimulator Configuration Panel**:
   - Dynamic list of stimulator configurations
   - Individual stimulator cards with type selection, date range, and arguments
   - Add/Remove stimulator buttons
   - Real-time argument configuration based on stimulator type

#### Features:
- **Stimulator Cards**: Each stimulator in the sequence gets its own card with:
  - Stimulator type selection dropdown
  - Date/time range picker
  - Dynamic argument configuration based on selected type
  - Remove button for individual stimulators
- **Add Stimulator Button**: Allows users to add new stimulators to the sequence
- **Responsive Design**: Interface adapts to different screen sizes

### 2. Controller Updates (`src/node/static/js/controllers/ethoscopeController.js`)

#### New Functions Added:

1. **`getSelectedStimulatorOption(name)`**
   - Retrieves the currently selected stimulator option object
   - Used to show stimulator descriptions and arguments

2. **`getStimulatorArguments(className)`**
   - Returns argument definitions for a specific stimulator class
   - Enables dynamic argument form generation

3. **`addNewStimulator()`**
   - Adds a new stimulator to the sequence
   - Initializes empty stimulator configuration

4. **`removeStimulator(index)`**
   - Removes stimulator at specified index
   - Updates the sequence array

5. **`updateStimulatorArguments(index)`**
   - Updates argument configuration when stimulator type changes
   - Sets default values for new stimulator arguments

#### Enhanced Functions:

1. **`update_user_options()`**
   - Added special handling for MultiStimulator initialization
   - Automatically creates initial stimulator when MultiStimulator is selected

### 3. CSS Styling (`src/node/static/css/main.css`)

#### New Styles Added:
- **Multi-stimulator container styling**: Clean, organized layout for the configuration interface
- **Stimulator card styling**: Individual cards for each stimulator with hover effects
- **Form styling**: Consistent styling for dropdowns, inputs, and date pickers
- **Button styling**: Styled add/remove buttons with hover animations
- **Responsive design**: Mobile-friendly adaptations

#### Design Features:
- Uses existing CSS variable color system for consistency
- Smooth transitions and hover effects
- Card-based layout for individual stimulators
- Clear visual hierarchy

## User Experience Flow

### Single Stimulator (Existing Functionality)
1. User selects stimulator type from dropdown
2. Stimulator description appears
3. Argument configuration form appears below
4. User configures arguments and starts tracking

### Multi-Stimulator (New Functionality)
1. User selects "MultiStimulator" from dropdown
2. Multi-stimulator configuration panel appears
3. Initial empty stimulator card is created
4. User can:
   - Select stimulator type for each card
   - Set date/time range for each stimulator
   - Configure individual stimulator arguments
   - Add additional stimulators
   - Remove unwanted stimulators
5. User starts tracking with complete sequence

## Configuration Format

The frontend generates the following data structure for MultiStimulator:

```javascript
{
  "interactor": {
    "name": "MultiStimulator",
    "arguments": {
      "stimulator_sequence": [
        {
          "class_name": "OptoMidlineCrossStimulator",
          "arguments": {"p": 0.8},
          "date_range": "2023-01-01 10:00:00>2023-01-02 10:00:00"
        },
        {
          "class_name": "SleepDepStimulator",
          "arguments": {"min_inactive_time": 120},
          "date_range": "2023-01-03 10:00:00>2023-01-04 10:00:00"
        }
      ]
    }
  }
}
```

## Backward Compatibility

- **Existing experiments**: Continue to work without changes
- **Single stimulator selection**: Preserves original radio button interface for non-interactor options
- **API compatibility**: Data format remains compatible with backend expectations
- **No breaking changes**: All existing functionality preserved

## Key Benefits

1. **Intuitive Interface**: Dropdown selection makes stimulator choice clearer
2. **Visual Organization**: Card-based layout makes complex configurations manageable
3. **Dynamic Configuration**: Arguments adapt automatically to selected stimulator type
4. **Scalable Design**: Easy to add unlimited stimulators to sequence
5. **Responsive**: Works on desktop and mobile devices
6. **Consistent Design**: Follows existing UI patterns and color schemes

## Technical Implementation Details

### Angular.js Integration
- Uses existing Angular.js framework and patterns
- Leverages existing form validation and data binding
- Integrates with existing date picker component
- Uses existing utility functions where possible

### Data Binding
- Two-way data binding for all form inputs
- Real-time updates when stimulator types change
- Automatic argument initialization with default values
- Dynamic form generation based on stimulator definitions

### Error Handling
- Graceful handling of missing stimulator definitions
- Safe navigation for nested object properties
- Fallback values for missing or invalid data

## Future Enhancements

Potential improvements for future releases:
1. **Drag-and-drop reordering** of stimulators in sequence
2. **Copy/paste functionality** for stimulator configurations
3. **Template system** for common stimulator sequences
4. **Visual timeline** showing stimulator activation periods
5. **Import/export** of stimulator sequence configurations
6. **Real-time validation** of date range overlaps

## Testing Recommendations

1. **Functionality Testing**:
   - Test dropdown selection for all stimulator types
   - Verify argument forms appear correctly for each type
   - Test add/remove stimulator functionality
   - Verify date range picker integration

2. **Data Validation Testing**:
   - Test with various stimulator combinations
   - Verify correct data structure generation
   - Test edge cases (empty sequences, invalid dates)

3. **UI/UX Testing**:
   - Test responsive design on different screen sizes
   - Verify accessibility (keyboard navigation, screen readers)
   - Test with long stimulator names and descriptions

4. **Integration Testing**:
   - Test complete tracking start flow with multi-stimulator
   - Verify backend receives correct data format
   - Test error handling and edge cases

The frontend implementation provides a comprehensive, user-friendly interface for configuring multiple stimulators while maintaining full backward compatibility with existing functionality.
