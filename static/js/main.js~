

if(window.addEventListener) {
window.addEventListener('load', function () {
  var TempROI, context, ROI, contexto, RoiObj, RoiObjList;
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
    console.log(oReq.status);
}
    
//// Load the ROI from the SM, previous saved ROI's
function ev_loadRoiFromSM(ev){
    var oReq = new XMLHttpRequest();
    oReq.open("get", "/ROI", false);
    oReq.send();
    
    RoiObjList=[];
    res = JSON.parse(oReq.response);
    
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
    var data = JSON.stringify({trackingType:2,roi:RoiObj})
    console.log(data)
    var oReq = new XMLHttpRequest();
    oReq.open("put", "/started", false);
    oReq.setRequestHeader('Content-Type', 'application/json; charset=UTF-8');
    oReq.send(data);
    console.log("start");
}
/// Stop
function ev_stop(){
    var oReq = new XMLHttpRequest();
    oReq.open("put", "/started", false);
    oReq.send();
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

//function handleRadio(){
//   selection = $('input[name=selectedRoi]:checked').val();
//    RoiObj = RoiObjList[selection];
//   img_update();
//}
