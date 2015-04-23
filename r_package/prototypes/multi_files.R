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
		stop("frhave at least a column names 'path'")
	
	file_dt[,file := basename(path)]
	setkey(file_dt, file)
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
	"/data/psv_results/2015-04-17_17-06-49_00016dfce6e94dee9bb1a845281b086e.db",
	"/data/psv_results/2015-04-17_17-09-18_00026dfce6e94dee9bb1a845281b086e.db",
	"/data/psv_results/2015-04-17_17-10-32_00036dfce6e94dee9bb1a845281b086e.db",
	"/data/psv_results/2015-04-17_17-11-11_00046dfce6e94dee9bb1a845281b086e.db")

conditions <- as.factor(c("ctrl", "quinine", "camphor_1", "camphor_2"))

ref <- data.table(path,conditions)


dt <- loadMultipleFiles(file_dt=ref, reference_hour = 10, FUN=interpolateROIData, fs=1/5.)


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


#~ d <- loadROIsFromFile(FILE, FUN=interpolateROIData,)
#~ 
#~ # compute activity for each ROI in place
#~ dt[,activity:=activity(x,y) , by=key(dt)]
#~ 
#~ 
#~ # exclude activity when sum <= 3
#~ activ <- dt[, list(mask=sum(activity) > 3),by=roi_id]
#~ good_rois <- activ[mask==T,roi_id]
#~ dt <- dt[.(good_rois)]
#~ 
#~ dt[,activity_filt:=filter(activity, rep(1, 601)) , by=key(dt)]
#~ #
#~ ggplot(data = dt, aes(x=t, y=activity, colour=as.factor(roi_id))) + geom_line()
#~ 

tp <- dt[,list(activity=mean(activity)) , by=c("t","conditions")]

setkey(tp,t)

tp[, filtered_act := filter(activity,rep(1/120,120)), by=c("conditions")]
tp[, h:=as.numeric(t/3600)]
ggplot(data = tp, aes(x=h, y=filtered_act, colour=as.factor(conditions))) + geom_line() + geom_vline(xintercept = 1:10*12)

dt[, roi_id := as.numeric(roi_id)]

dt[,x_rel:=ifelse(roi_id > 16, 1-x,x)]

ggplot(dt, aes(x=x_rel)) + geom_density(aes(group=conditions, colour=conditions, fill=conditions), alpha=0.3)
