

if(window.addEventListener) {
window.addEventListener('load', function () {
  var TempROI, context, ROI, contexto, RoiObj, RoiObjList, flydata="";
//  var ROIObj = {
//                ROI:[],
//                pointsToTrack:1,
//                referencePoints:[],
//  };
  RoiObj = {
                name:"Default",
                rois:[],
  };
    
    RoiObjList = [];
  
function init () {
    
    // Find the canvas element.
    ROI = document.getElementById('ROIView');
    if (!ROI) {
      alert('Error: I cannot find the canvas element!');
      return;
    }

    if (!ROI.getContext) {
      alert('Error: no canvas.getContext!');
      return;
    }

    // Get the 2D canvas context.
    contexto = ROI.getContext('2d');
    if (!contexto) {
      alert('Error: failed to getContext!');
      return;
    }

    // Add the temporary canvas.
    var container = ROI.parentNode;
    TempROI = document.createElement('canvas');
    if (!TempROI) {
      alert('Error: I cannot create a new canvas element!');
      return;
    }

    TempROI.id     = 'drawingCanvas';
    TempROI.width  = ROI.width;
    TempROI.height = ROI.height;
    container.appendChild(TempROI);

    context = TempROI.getContext('2d');

    tool = new rect();
      
    
    // Attach the mousedown, mousemove and mouseup event listeners.
    TempROI.addEventListener('mousedown', ev_canvas, false);
    TempROI.addEventListener('mousemove', ev_canvas, false);
    TempROI.addEventListener('mouseup',   ev_canvas, false);
    
    //buttons actions
    removeLast = document.getElementById('removeLast');
    autoMask = document.getElementById('autoMask');
    saveRoiToSM = document.getElementById('saveRoi');
    loadRoiFromSM = document.getElementById('loadRoi');
    refreshBackground = document.getElementById('refreshBackground');
    start = document.getElementById('start');
    stop = document.getElementById('stop');
    
    removeLast.addEventListener('click', ev_remove, false);
    autoMask.addEventListener('click',ev_autoMask, false);
    saveRoiToSM.addEventListener('click', ev_saveRoiToSM, false);
    loadRoiFromSM.addEventListener('click', ev_loadRoiFromSM, false);
    refreshBackground.addEventListener('click', ev_refreshBackground, false);
    start.addEventListener('click', ev_start, false);
    stop.addEventListener('click', ev_stop, false);

  }

  // The general-purpose event handler. This function just determines the mouse 
  // position relative to the canvas element.
  function ev_canvas (ev) {
    if (ev.layerX || ev.layerX == 0) { // Firefox
      ev._x = ev.layerX;
      ev._y = ev.layerY;
    } else if (ev.offsetX || ev.offsetX == 0) { // Opera
      ev._x = ev.offsetX;
      ev._y = ev.offsetY;
    }

    // Call the event handler of the tool.
    var func = tool[ev.type];
    if (func) {
      func(ev);
    } 
  }

  function img_update () {
      contexto.clearRect(0, 0, TempROI.width, TempROI.height);
      var l = RoiObj.rois.length;
      var img = new Image(); 
      var num = Math.random().toString(36).substring(7)
      img.src = '/static/img/0.jpg?id='+num;
      img.onload = function(){
        contexto.drawImage(img, 0,0, TempROI.width, TempROI.height );
         for(var i = 0; i < l; i++){
            //contexto.drawImage(TempROI, 0, 0);
            console.log(RoiObj.rois[i].ROI[0]);
            contexto.strokeStyle="yellow";
            contexto.strokeRect(RoiObj.rois[i].ROI[0],
                                RoiObj.rois[i].ROI[1],
                                RoiObj.rois[i].ROI[4],
                                RoiObj.rois[i].ROI[5]);
         }
        //contexto.stroke();
        context.clearRect(0, 0, TempROI.width, TempROI.height);
      };
  }
    
  function saveRoi (ev){
      console.log(ev._x);
      console.log(ev._y);
      console.log(tool.x0);
      console.log(tool.y0);
      
      var x  = Math.min(ev._x,  tool.x0),
          y  = Math.min(ev._y,  tool.y0),
          w  = Math.abs(ev._x - tool.x0),
          h  = Math.abs(ev._y - tool.y0),
          x1 = Math.max(ev._x,  tool.x0),
          y1 = Math.max(ev._y,  tool.y0);
     
      //construct Roi object
      r = {};
      r.ROI = [x,y,x1,y1,w,h];
      r.pointsToTrack = 1;
      r.referencePoints = [x+w/2.,y+h/2.];
      RoiObj.rois.push(r);
      console.log(RoiObj.rois);
      console.log(x,y,w,h, x1, y1);
  }

  // The rectangle tool.
  rect = function () {
    var tool = this;
    this.started = false;

    this.mousedown = function (ev) {
      tool.started = true;
      tool.x0 = ev._x;
      tool.y0 = ev._y;
    };

    this.mousemove = function (ev) {
      if (!tool.started) {
        return;
      }

      var x = Math.min(ev._x,  tool.x0),
          y = Math.min(ev._y,  tool.y0),
          w = Math.abs(ev._x - tool.x0),
          h = Math.abs(ev._y - tool.y0);

      context.clearRect(0, 0, TempROI.width, TempROI.height);

      if (!w || !h) {
        return;
      }
      context.strokeStyle="yellow";
      context.strokeRect(x, y, w, h);
    };

    this.mouseup = function (ev) {
      if (tool.started) {
        tool.mousemove(ev);
        tool.started = false;
        saveRoi(ev);
        img_update();
        
      }
    };
  };
//// Remove function
    function ev_remove(ev){
        RoiObj.rois.pop();
        console.log(RoiObj);
        img_update();
    };
    
//// Auto Mask
    function ev_autoMask(ev){
        //take the first rectangle from roiObj
        var r = RoiObj.rois[0];
        //Divide the recntangle in a table of 16 rows 2 columns
        x = r.ROI[0];
        y = r.ROI[1];
        w = r.ROI[4];
        h = r.ROI[5];
        
        var individualW = w/2;
        var individualH = h/16;
        
        RoiObj.rois=[];
        for (var j=0; j<2; j++){
            for(var i = 0; i < 16; i++){
                 var d = {};
                 dx = Math.round(x + individualW*j);
                 dx1 = Math.round(dx + individualW);
                 dy = Math.round(y + individualH*i);
                 dy1 = Math.round(dy + individualH);

                 d.ROI = [dx,dy, dx1,dy1,individualW,individualH];
                console.log(d.ROI);
                 d.pointsToTrack = 1;
                 d.referencePoints = [];
                 RoiObj.rois.push(d);
            }
        }
        img_update();
        console.log("auto good");
    };
///// Background image paint    
function backgroundImage(){
    var img = new Image(); 
    var num = Math.random().toString(36).substring(7)
    img.src = '/static/img/0.jpg?id='+num;
    img.onload = function(){
        contexto.drawImage(img, 0,0, TempROI.width, TempROI.height );
        console.log("loaded");
    };
    
}
    

/// Save ROI into SM for future trackings.
function ev_saveRoiToSM(ev){
    var name = prompt("What is the name of this ROI", "Default");
    RoiObj.name = name;
    data = JSON.stringify(RoiObj);
    var oReq = new XMLHttpRequest();
    oReq.open("post", "/ROI", false);
    oReq.setRequestHeader('Content-Type', 'application/json; charset=UTF-8');
    oReq.send(data);
    console.log(data);
    console.log(oReq.status);
}
    
//// Load the ROI from the SM, previous saved ROI's
function ev_loadRoiFromSM(ev){
    var oReq = new XMLHttpRequest();
    oReq.open("get", "/ROI", false);
    oReq.send();
    
    RoiObjList=[];
    console.log(oReq.response);
    res = JSON.parse(oReq.response);
    console.log(res);
    
    if (res.name == 'Rois Saved in SM'){        
        for (var d in res.data){
           RoiObjList.push(res.data[d]);
        }
        console.log(RoiObjList);
        var l = RoiObjList.length;
        console.log(l);
        $('#pickloaded').append(
                "<ul class='list-group'></ul>"
            );
        for(var i=0; i<l; i++){
            $('#pickloaded ul').append(
                "<li class='list-group-item'><input type='radio' name='selectedRoi' id='selectedRoi"+i+"' value="+i+">"+RoiObjList[i].name+"</li>"
            );
        }

        for(var i=0; i<l; i++){
             //Radio Buttons
             id = 'selectedRoi'+i;
             console.log(id);
             element = document.getElementById(id);
             //radioButtonsArray.push(element);
             element.addEventListener('click', ev_handlerRadio, false);
        }
        console.log("load");
    }
}    

/// Refresh
function ev_refreshBackground(){
    var oReq = new XMLHttpRequest();
    oReq.open("get", "/refresh", false);
    oReq.setRequestHeader('Content-Type', 'text/html; charset=UTF-8');
    oReq.send();
    console.log("refresh");
    img_update();
}
    
/// Start
function ev_start(){
    var tracking = $('input[name=optionTrack]:checked').val();
    var d = new Date();
    var t = d.getTime();
    if (RoiObj.rois.length<1){
        alert("There is no ROI selected. You can't start tracking.");
    }else if (typeof tracking == 'undefined'){
        alert("There is no tracking type selected. You can't start tracking.");
    }else{
        var data = JSON.stringify({time:t,trackingType:tracking,roi:RoiObj}); 
        var oReq = new XMLHttpRequest();
        oReq.open("put", "/started", false);
        oReq.setRequestHeader('Content-Type', 'application/json; charset=UTF-8');
        oReq.send(data);
        console.log("start");
        console.log(t);
        console.log(data);
        location.reload();
    }

}
/// Stop
function ev_stop(){
    var oReq = new XMLHttpRequest();
    oReq.open("put", "/started", false);
    oReq.send();
    location.reload();
    console.log("stop");
}

/// Radio Buttons Handdle
function ev_handlerRadio(){
   selection = $('input[name=selectedRoi]:checked').val();
   RoiObj = RoiObjList[selection];
   console.log(RoiObj);
   img_update();
   $('#pickloaded').empty();
}



  init();
  backgroundImage();
  

    
}, false); }

(function(){

///// Angular
var app = angular.module('fly', []);
//var internalID = window.setInterval(last_data, 10000);  
var flydata = "";

app.config(function($interpolateProvider) {
 $interpolateProvider.startSymbol('{!');
  $interpolateProvider.endSymbol('!}');
});

app.controller('flyDataCtrl',['$http','$interval', function ($http, $interval){
   var flydata = this;
   flydata.data = "";
    var i = 0;
    function getData(){
   $http.get("/websocket").success(function(data){
      flydata.data = data;
   })};
    getData();
   $interval(getData, 60000);

}]);

app.controller('changeMachineIdCtrl',['$scope', '$http',function($scope,$http){
        $scope.changeName = function(){
            var name = prompt("New name for this Sleep", "SM 01");
            $http.post("/changeMachineId", JSON.stringify({"newName":name})).success(function(data){
            $("#machineid").text(data);
            }); 
        };
}]);
    
app.controller('deleteDataCtrl',['$scope', '$http',function($scope,$http){
        $scope.deleteData = function(){
            var d = confirm("Are You sure you want to delete all the data?");
            if(d == true){
                var mid = $("#machineid").text();
                $http.delete("/deleteData/"+mid); 
            }
        };
}]);
app.controller('poweroffCtrl',['$scope', '$http',function($scope,$http){
    $scope.poweroff = function(){
        var c = confirm("Are You sure you want to poweroff the sleep Monitor?");
        if(c == true){
            var mid = $("#machineid").text();
            $http.put("/poweroff/"+mid); 
        }
    };
}]);
<<<<<<< HEAD
app.controller('uploadCtrl',['$scope', '$http',function($scope,$http){
           $scope.upload = function(){  
              var ext = $('#data').val().split('.').pop().toLowerCase();
             
              if (confirm("WARNING: updating the package will stop tracking. Do you wish to continue?")) {
                    if($.inArray(ext, ['zip']) == -1) {
                         alert('File must be in .zip format.');
                         return false;
                     } else {
                         var form_data = new FormData($('#upload-file')[0]);
                          console.log(form_data);
                         $http.post("/update", form_data, { headers: {"Content-type"  : "application/x-www-form-urlencoded; charset=utf-8";}}).success(function(data) {
                                 setTimeout(function() {alert("File uploaded successfully. Please restart tracking.")}, 5000);
                             });
                     }
              } else {
                 return false;
              }
          };
}]);
=======
>>>>>>> 2c18142d99048230a47ad507b4237c753bbd75ed

})(); 

//function handleRadio(){
//   selection = $('input[name=selectedRoi]:checked').val();
//    RoiObj = RoiObjList[selection];
//   img_update();
//}
