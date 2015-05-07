rm(list=ls())
library(risonno)
library(data.table)
library(ggplot2)


sleepAnalysis <- function(data,
			fs=2.0, #Hz
			min_time_immobile=60*5, #s
			time_window_length=10, #s
			activity_threshold=.03 # proportion of tube length
			){ 
	d <- copy(data)
	#1 curate data
	# TODO
	d <- d
	
	#2 interpolate
	d <- interpolateROIData(d, fs)
	d[,activity:=activity(x,y)]
	d <- interpolateROIData(d, 1/time_window_length)
	
	
	


	d[,moving := ifelse(activity > activity_threshold / time_window_length, TRUE, FALSE)]
	d[,asleep := sleep_contiguous(moving,1/time_window_length)]

	}



activity <- function(x,y){
	comp = x + 1i*y
	distance <- c(0, abs(diff(comp)))
	return(distance)
}


sleep_contiguous <- function(moving,fs,min_valid_time=5*60){
	min_len <- fs * min_valid_time
	r_sleep <- rle(!moving)
	valid_runs <-  r_sleep$length > min_len 
	r_sleep$values <- valid_runs & r_sleep$value
	inverse.rle(r_sleep)
}

#'
#'path <- "/data/validation/validation_out.db"
#'rois <- c(1:3,5:19,21:32)
#'d1 <- loadROIsFromFile(path, rois=rois, reference_hour = 9, FUN=sleepAnalysis,max_time=3600*20)
#'d1[,condition:="wet"]
#'
#'path <- "/data/psv_results/00016dfce6e94dee9bb1a845281b086e/GGSM-001/2015-04-17_17-06-49/2015-04-17_17-06-49_00016dfce6e94dee9bb1a845281b086e.db"
#'rois <- c(2:15,18:31)
#'d2 <- loadROIsFromFile(path, rois=rois, reference_hour = 9, FUN=sleepAnalysis,max_time=3600*20)
#'d2[,condition:="dry"]
#'
#'d <- rbind(d1,d2)
#'d[,x:=ifelse(roi_id > 16, 1-x,x)]
#'
#'print(
#'	ggplot(d[asleep==T,], aes(x=x, fill=condition)) + geom_density(alpha=.3)  + 
#'		ggtitle("Position in the tube when ASLEEP\n~30 flies, 24h")
#')
#'
#'print(
#'	ggplot(d[asleep==F,], aes(x=x, fill=condition)) + geom_density(alpha=.3)  + 
#'		ggtitle("Position in the tube when ACTIVE\n~30 flies, 24h")
#')
#'
#'ggplot(d, aes(x=x, fill=condition,linetype=asleep)) + geom_density(alpha=.3) 
