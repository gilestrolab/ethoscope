rm(list=ls())
library(risonno)
library(data.table)
library(ggplot2)


path <- c(
	"/data/psv_results/00016dfce6e94dee9bb1a845281b086e/GGSM-001/2015-04-17_17-06-49/2015-04-17_17-06-49_00016dfce6e94dee9bb1a845281b086e.db",
	"/data/psv_results/00026dfce6e94dee9bb1a845281b086e/GGSM-002/2015-04-17_17-09-18/2015-04-17_17-09-18_00026dfce6e94dee9bb1a845281b086e.db"
#~  	"/data/psv_results/00036dfce6e94dee9bb1a845281b086e/GGSM-003/2015-04-17_17-10-32/2015-04-17_17-10-32_00036dfce6e94dee9bb1a845281b086e.db",
#~  	"/data/psv_results/00046dfce6e94dee9bb1a845281b086e/GGSM-004/2015-04-17_17-11-11/2015-04-17_17-11-11_00046dfce6e94dee9bb1a845281b086e.db"
	)

conditions <- as.factor(c("ctrl", "quinine"))#, "camphor_1", "camphor_2"))

ref <- data.table(path,conditions)

dt <- loadMultipleFiles(files=ref, rois=c(2:15,17:31), reference_hour = 9)


activity <- function(x,y){
	comp = x + 1i*y
	distance <- c(0, abs(diff(comp)))
	return(distance)
}


dt[,activity:=activity(x,y) , by=key(dt)]


tp <- dt[,list(activity=mean(activity)) , 
		by=c("t","conditions")
			]

function(fs,bys){
	#1. aggregate by time (arithmetic mean)
	#2. aggregate using the bys
	#3. subset :
		# a. time wise (e.g. show me all the data between t1 and t2)
		# b. condition wise e.g. show me only condition == female
}

setkey(tp,t)

tp[, filtered_act := filter(activity,rep(1/241,241)), by=c("conditions")]
tp[, h:= t/3600]
ggplot(data = tp, aes(x=h, y=filtered_act, colour=as.factor(conditions))) + geom_line() + geom_vline(xintercept = 1:14*12)


dt[,x_rel:=ifelse(roi_id > 16, 1-x,x)]
dt[,x2:=ifelse(x_rel > .95,.95,x_rel) ]
ggplot(dt[t>5*24*3600], aes(x=x2)) + geom_density(aes(group=conditions, colour=conditions, fill=conditions), alpha=0.3)
ggplot(dt, aes(x=x2)) + geom_density(aes(group=conditions, colour=conditions, fill=conditions), alpha=0.3)
