rm(list=ls())
library(risonno)
library(pracma)
library(zoo)
library(data.table)
library(ggplot2)


activity <- function(x,y){
	comp = x + 1i*y
	distance <- c(0, abs(diff(comp)))
	return(distance)
}

# read a file

loadMultipleFiles <- function(file_dt, FUN=NULL, ...){
	file_dt <- as.data.table(file_dt)

	if(!("path" %in% colnames(file_dt)))
		stop("file_dt should be a dataframe with, at least, a column names 'path'")
	
	file_dt[,file := basename(path)]
	setkey(file_dt, file)
	#print(file_dt[,file])
	dup <- anyDuplicated(file_dt[,file])
	if(dup != 0)
		stop(
			sprintf("Duplicated file name: %s",file_dt[dup,file])
			)


	
	
	l_dt <- lapply(file_dt[,path], function(x){
			loadROIsFromFile(x, add_file_name=T, FUN=FUN, ...)
		}
		)
	
	out <- rbindlist(l_dt)
	setkeyv(out, key(l_dt[[1]]))
	out <- file_dt[out]
	setkeyv(out, key(l_dt[[1]]))
	return(out)
	} 

path <- c(
	"/data/psv_results/00016dfce6e94dee9bb1a845281b086e/GGSM-001/2015-04-17_17-06-49/2015-04-17_17-06-49_00016dfce6e94dee9bb1a845281b086e.db",
	"/data/psv_results/00026dfce6e94dee9bb1a845281b086e/GGSM-002/2015-04-17_17-09-18/2015-04-17_17-09-18_00026dfce6e94dee9bb1a845281b086e.db"
#~ 	"/data/psv_results/00036dfce6e94dee9bb1a845281b086e/GGSM-003/2015-04-17_17-10-32/2015-04-17_17-10-32_00036dfce6e94dee9bb1a845281b086e.db",
#~ 	"/data/psv_results/00046dfce6e94dee9bb1a845281b086e/GGSM-004/2015-04-17_17-11-11/2015-04-17_17-11-11_00046dfce6e94dee9bb1a845281b086e.db"
	)

#~ conditions <- as.factor(c("ctrl", "quinine", "camphor_1", "camphor_2"))
conditions <- as.factor(c("ctrl", "quinine"))#, "camphor_1", "camphor_2"))

ref <- data.table(path,conditions)


dtr <- loadMultipleFiles(file_dt=ref, rois=4:10, reference_hour = 9, FUN=interpolateROIData, fs=1/5.)

stop("OK")

activity <- function(x,y){
	comp = x + 1i*y
	distance <- c(0, abs(diff(comp)))
	return(distance)
}
# compute activity for each ROI in place

#fixme
dt[, t := as.numeric(t)]
dt[, x := as.numeric(x)]
dt[, y := as.numeric(y)]


dt[,activity:=activity(x,y) , by=key(dt)]


tp <- dt[,list(activity=mean(activity)) , by=c("t","conditions")]

setkey(tp,t)

tp[, filtered_act := filter(activity,rep(1/241,241)), by=c("conditions")]
tp[, h:=as.numeric(t/3600)]
ggplot(data = tp, aes(x=h, y=filtered_act, colour=as.factor(conditions))) + geom_line() + geom_vline(xintercept = 1:14*12)

dt[, roi_id := as.numeric(roi_id)]

dt[,x_rel:=ifelse(roi_id > 16, 1-x,x)]
dt[,x2:=ifelse(x_rel > .95,.95,x_rel) ]
ggplot(dt[t>5*24*3600], aes(x=x2)) + geom_density(aes(group=conditions, colour=conditions, fill=conditions), alpha=0.3)
ggplot(dt, aes(x=x2)) + geom_density(aes(group=conditions, colour=conditions, fill=conditions), alpha=0.3)
