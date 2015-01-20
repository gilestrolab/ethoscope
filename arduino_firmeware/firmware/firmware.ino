/*
 * sleep_deprivator_fw.ino
 * 
 * Copyright 2013 Giorgio Gilestro <giorgio@gilest.ro>
 * 
 * This program is free software; you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation; either version 2 of the License, or
 * (at your option) any later version.
 * 
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 * 
 * You should have received a copy of the GNU General Public License
 * along with this program; if not, write to the Free Software
 * Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
 * MA 02110-1301, USA.
 * 
 * 
 * 
 * This is the firmware for the sleep deprivator created in the Gilestro
 * laboratory at Imperial College London and produced and distributed
 * by PolygonalTree.co.uk
 * 
 * HARDWARE
 * 
 * Servo board for controlling the motors: http://www.emartee.com/product/42016/
 * Connections to motors: http://letsmakerobots.com/node/25923
 * plug monitor 1 / channel 1 to A9 (D63) and go down skipping 44,45,46,2,3,5,6,7,8,11,12
 * Motors: Turnigy TG9e http://www.hobbyking.com/hobbyking/store/__30946__Turnigy_TG9e_9g_1_5kg_0_10sec_Eco_Micro_Servo_UK_Warehouse_.html
 * 
 * FIRMWARE LIBRARY NEEDED
 * For information on installing libraries, see: http://arduino.cc/en/Guide/Libraries

 * Servo library http://arduino.cc/en/reference/servo
 * SerialCommand Library https://github.com/kroimon/Arduino-SerialCommand
 * 
 * 
 * The servos are connected as follow:
 * Row 1: (16-01) 22,23,24,25, 26,27,28,29, 30,31,32,33, 34,35,36,37
 * Row 2: (17-32) 38,39,40,41, 42,43,44,45, 46,47,48,49, 50,51,52,53
 * 
 * In windows, an easy way to make an upgrade without using the Arduino IDE is
 * to adopt XLoader http://xloader.russemotto.com/
 * 
 */

#include <Servo.h> 
#include <SerialCommand.h>

const String VERSION = "0.99";
const int SERVO_NUMBER = 32;
const int LEFT_POSITION = 0;
const int RIGHT_POSITION = 178;

/* 32 --- 17
 * 16 --- 01
 */
 /*
 const int servoPINS[SERVO_NUMBER] = {37,36,35,34, 33,32,31,30, 29,28,27,26, 25,24,23,22,
                                      38,39,40,41, 42,43,44,45, 46,47,48,49, 50,51,52,53};
 
*/
const int servoPINS[SERVO_NUMBER] = {37,38,36,39,35,40,34,41,33,42,32,43,31,44,30,45,
                                     29,46,28,47,27,48,26,49,25,50,24,51,23,52,22,53};

Servo servoarray[SERVO_NUMBER];
SerialCommand sCmd; // The SerialCommand object


int SHAKE = 2; // number of times the servo rotates
int ROTATION_DELAY = 600; // pause between each motor movement
int GROUP_SIZE = 1; // the size of the group of motors rotating at once

boolean USE_SERVO = true;
boolean NEW_SERVO = true;
boolean DEBUG_MODE = false;

boolean AUTO_MODE = false; // set this to TRUE to use it without PC connected
int rMIN = 1; // default minimal value for RANDOM rotations in AUTO mode
int rMAX = 2; // default maximum value for RANDOM rotations in AUTO mode

int lap = 1; // used internally
unsigned long pTime = 0; // used internally

int LED = 13; //status LED




//prototypes//
void listValues();
void moveServo(int channel);
void printError(const char *command);
void printHelp();
void moveServoGroup(int bat[]);

// ================= CHANGE DEFAULT VALUES FUNCTIONS ================== //

void changeSHAKE(){
  //change the default value for the number of SHAKE
  //
  char *arg;
  arg = sCmd.next();
  if (arg != NULL) {
    SHAKE = atoi(arg);
  }
  listValues();
}

void toggleAUTOMODE(){
  //Set Automode ON or OFF
  //
  AUTO_MODE = not AUTO_MODE;
  digitalWrite(LED, AUTO_MODE);
  listValues();
}


void toggleDEBUGMODE(){
  //Set DEBUG MODE ON or OFF
  //
  DEBUG_MODE = not DEBUG_MODE;
  listValues();
}

void changeDELAY(){
  //Changes the default value for the pause between the two rotations
  //value in milliseconds
  char *arg;
  arg = sCmd.next();
  if (arg != NULL) {
    ROTATION_DELAY = atoi(arg);
  }
  listValues();
}

void changeGROUP(){
  //Changes the default value for the group size of motors moving at once
  char *arg;
  arg = sCmd.next();
  if (arg != NULL) {
    GROUP_SIZE = atoi(arg);
  }
  listValues();
}

void changeRANDOM_INTERVALS(){
  char *arg;

  arg = sCmd.next();
  if (arg != NULL) {
    rMIN = atoi(arg);
  }

  arg = sCmd.next();
  if (arg != NULL) {
    rMAX = atoi(arg);
  }
  listValues();
}

// ================= TIME FUNCTIONS ================== //

String uptime()
{
  long unsigned currentmillis = millis();

  static char secs_f[3];
  static char mins_f[3];
  static char hours_f[3];
  
  long unsigned secs = currentmillis/1000; //convect milliseconds to seconds
  long unsigned mins=secs/60; //convert seconds to minutes
  long unsigned hours=mins/60; //convert minutes to hours
  
  secs=secs-(mins*60); //subtract the coverted seconds to minutes in order to display 59 secs max 
  mins=mins-(hours*60); //subtract the coverted minutes to hours in order to display 59 minutes max
  
  sprintf(secs_f, "%02d", secs);
  sprintf(mins_f, "%02d", mins);
  sprintf(hours_f, "%02d", hours);

  String time = String(hours_f) + ":" + String(mins_f) + ":" + String(secs_f);
  
  return time;
}


int get_new_interval() {

  int rand = random(rMIN, rMAX); //random number between rMIN, rMAX
  pTime = millis();
  if ( DEBUG_MODE ) { Serial.println( "Next rotation in " + String(rand) + " minutes" ); }
  return rand;
}

boolean time_elapsed() {
  unsigned long time = millis();
  return (time - pTime >= lap*60000);
}

unsigned long remaining_time() {
  unsigned long time = millis();
  return ( (lap*60000  - (time - pTime)) / 1000 );
}
    

// ================= ROTATE FUNCTIONS ================== //


void resetPosition(){

//Modified by Luis with commit  c995f6bc95ab71e46feb9ec187e970505ed5a460 
//Not sure this is right though
//Attach some servos to prevent the servo blocking state

 for (int i=0; i<SERVO_NUMBER-15; i++){
    pinMode(servoPINS[i],OUTPUT);
    servoarray[i].attach(servoPINS[i], 740, 2250);
    servoarray[i].write(90);
    Serial.println(servoarray[i].read());
}
   
 Serial.println("Cleaning servos. Wait..");
 
 for (int i=0; i<SERVO_NUMBER; i++){
   pinMode(servoPINS[i],OUTPUT);
   servoarray[i].detach();
   servoarray[i].attach(servoPINS[i], 740, 2250);
   Serial.println(servoarray[i].read());
   servoarray[i].write(90);
   delay(ROTATION_DELAY);
   servoarray[i].detach();
 }
}


void moveChannel() {
  //Move only the specified channel (1-SERVO_NUMBER)
  int channel;
  char *arg;

  arg = sCmd.next();
  if (arg != NULL) {
    channel = atoi(arg);
  }
  
  if ( channel >= 1 && channel <= SERVO_NUMBER )
  {
    int pin = servoPINS[channel-1];
    moveServo(channel);
    
    Serial.println("OK C" + String(channel) + "P" + String(pin) );
  }
  else {
    printError("");
  }
}

void moveServo(int channel) {
  //move a single servo
  if ( USE_SERVO )
  {
    servoarray[channel-1].attach(servoPINS[channel-1]);
    for( int s = 0; s < SHAKE; s++)
    {
      servoarray[channel-1].write(LEFT_POSITION);
      delay(ROTATION_DELAY);
      servoarray[channel-1].write(RIGHT_POSITION);
      delay(ROTATION_DELAY);
      servoarray[channel-1].write(90);
      delay(ROTATION_DELAY);
    }
    servoarray[channel-1].detach();
  }
  
}  

void rotatesAll() {
  //rotates all at once, group by group
  int bat[GROUP_SIZE];
  
  if ( DEBUG_MODE ) { Serial.println("Moving all in groups of " + String(GROUP_SIZE)); }
  
  for (int g = 0; g < SERVO_NUMBER / GROUP_SIZE; g++) {
    for (int c = 0; c < GROUP_SIZE; c++)
    {
      bat[c] = g*GROUP_SIZE + c + 1; //channel
    }
    moveServoGroup(bat);
  } 
}

void moveServoGroup(int bat[]) {
    //move a group of servo
    //bat is an array containing the channels to be moved, 1-32 (e.g: 1,2,3,4)

  const int DELAY_BTWN_ATTACH = 10;
  
  if ( DEBUG_MODE ) { 
    
    for (int i = 0; i<GROUP_SIZE; i++) {
      Serial.print("Moving channel:" + String(bat[i]) + " ");
      Serial.println(" with PIN: " + String(servoPINS[bat[i]-1]));
    }
  }
  
  for (int i = 0; i < GROUP_SIZE; i++) {
    servoarray[bat[i]-1].attach(servoPINS[bat[i]-1]);
    //delay(DELAY_BTWN_ATTACH);
  }
  
  for( int s = 0; s < SHAKE; s++)
  {
    for (int i = 0; i<GROUP_SIZE; i++) {
      servoarray[bat[i]-1].write(LEFT_POSITION);
    }
    delay(ROTATION_DELAY);

    for (int i = 0; i<GROUP_SIZE; i++) {
      servoarray[bat[i]-1].write(RIGHT_POSITION);
    }
    delay(ROTATION_DELAY);
    for (int i = 0; i<GROUP_SIZE; i++) {
      servoarray[bat[i]-1].write(90);
    }
    delay(ROTATION_DELAY);
  }
  
  for (int i = 0; i < GROUP_SIZE; i++) {
    servoarray[bat[i]-1].detach();
    //delay(DELAY_BTWN_ATTACH);
  }
  
  
}

// ================= PRINT FUNCTIONS ================== //


void setupSerialCommands() {
 sCmd.addCommand("HELP", printHelp);    
 sCmd.addCommand("L",     listValues);

 sCmd.addCommand("M",     moveChannel); // Takes one argument (1-SERVO_NUMBER). Move servo associated to channel
 sCmd.addCommand("S",     changeSHAKE); // Takes one argument. Change the SHAKE pattern; default 2
 sCmd.addCommand("D",     changeDELAY); // Takes one argument. Change the rotation delay; default 500ms
 sCmd.addCommand("G",     changeGROUP); // Takes one argument. Change the group size; default 4
 sCmd.addCommand("R",     changeRANDOM_INTERVALS); // Takes two arguments. Change the random intervals values
 sCmd.addCommand("AUTO",  toggleAUTOMODE); // Start autoMode (keep rotating at random intervals of xx-yy minutes)
 sCmd.addCommand("DEBUG",  toggleDEBUGMODE); // Start autoMode (keep rotating at random intervals of xx-yy minutes)

 sCmd.addCommand("ST",    rotatesAll); //rotates all at once

 sCmd.setDefaultHandler(printError);      // Handler for command that isn't matched  (says "What?")
}

void printHelp() {
  Serial.println("AUTO              Toggle Auto Mode ON or OFF");
  Serial.println("DEBUG             Toggle DEBUG Mode ON or OFF");
  Serial.println("S xx              Changes the SHAKE number (default 2)");
  Serial.println("G xx              Changes the GROUP number (default 4)");
  Serial.println("D xxx             Changes the DELAY between motor movements (default 500)");
  Serial.println("R min max         Changes the random INTERVALS parameters (default 1 7 minutes)");
  Serial.println("L                 List currently set values");
  Serial.println("M xx              Moves Channel xx (1-SERVO_NUMBER)");
  Serial.println("ST                Rotate all servos in groups of xx");
  Serial.println("HELP              Print this help message");
  Serial.println("=================================================================================");
}

void listValues(){
  String OFFON[2] = {"OFF","ON"};
  
  Serial.println("Version: " + VERSION);
  Serial.println("Uptime: " + String ( uptime() ));
  Serial.println("Automode: " + OFFON[AUTO_MODE] );
  Serial.println("Shake number: " + String(SHAKE) );
  Serial.println("Group Size: " + String(GROUP_SIZE));
  Serial.println("Motion Delay: " + String(ROTATION_DELAY));
  Serial.println("RANDOM intervals: " + String(rMIN) + " - " + String(rMAX) );
  Serial.println("Rotation delay: " + String(ROTATION_DELAY) );
  Serial.println("Voltage: " + String(analogRead(0)));
  Serial.println("Next rotation in : " + String(remaining_time()));
  Serial.println("=================================================================================");
}

void printError(const char *command) {
  // This gets set as the default handler, and gets called when no other command matches.
  Serial.println("ERROR Command not valid");
}


void setup() 
{ 

 Serial.begin(57600);
 setupSerialCommands();

 if ( NEW_SERVO ) {
    resetPosition() ;
 }
 pinMode(LED, OUTPUT);

 Serial.println("Ready.");

}


void loop()
{

  sCmd.readSerial(); 

  if ( AUTO_MODE and time_elapsed() ) {
    lap = get_new_interval();
    rotatesAll();
  }

}

