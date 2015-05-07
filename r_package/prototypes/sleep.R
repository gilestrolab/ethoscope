
totalWlkdDistClassif <- function(d,activity_threshold=.03){
	
	d[,activity := activity(x,y)]
	d_small <- d[,list(activity = sum(activity)), by=key(d)]
	d_small[, moving :=  ifelse(activity > activity_threshold, TRUE,FALSE)]
	d$activity <- NULL
	d_small
	}

sleepAnalysis <- function(data,
			time_window_length=10, #s
			min_time_immobile=60*5, #s
			motion_classifier_FUN=totalWlkdDistClassif,
			...
			){ 
	d <- copy(data)
	ori_keys <- key(d)
	#1 curate data
	# TODO
	d <- d
	
	d[, t := time_window_length * round(d[,t] /time_window_length)]
	setkeyv(d, "t")

#	d_small <- totalWlkdDistClassif(d)
	d_small <- motion_classifier_FUN(d,...)
	
	d_small <- unique(d_small[d])
	
	
	t_out <- seq(from=d_small[1,t], to=d_small[.N,t], by=time_window_length)
	

	d_small <- merge(d_small, data.table(t=t_out,key="t"),all=T)
	d_small[,moving := ifelse(is.na(moving), F, moving)]
	d_small[,asleep := sleep_contiguous(moving,1/time_window_length)]
	
	d_small <- d_small[,lapply(.SD,na.locf,na.rm=F)]
	
	setkeyv(d_small, ori_keys)
	
	d_small
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


file <- "/tmp/Rtmpb3NyFW/db_files/validation.db"
map <- data.frame(path=file, roi_id=2)
dt <- loadPsvData(map)
slp <- sleepAnalysis(dt)

dt2 <- loadPsvData(file,FUN=sleepAnalysis)
#'dt2 <- loadPsvData(file,FUN=sleepAnalysis)
