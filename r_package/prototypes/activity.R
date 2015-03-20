rm(list=ls())
library(risonno)
library(ggplot2)


activity <- function(x,y){
	comp = x + 1i*y
	distance <- c(0, abs(diff(comp)))
	return(distance)
}

# read a file
FILE <- "./test_data/short_data.db"
conditions <- cbind(roi_id=1:32, expand.grid(treatment=c(T,F), genotype=LETTERS[1:4]))
dt <- loadROIsFromFile(FILE, FUN=interpolateROIData, fs=1, condition_df = conditions)

# compute activity for each ROI in place
dt[,activity:=activity(x,y) , by=key(dt)]


# exclude activity when sum <= 3
activ <- dt[, list(mask=sum(activity) > 3),by=roi_id]
good_rois <- activ[mask==T,roi_id]
dt <- dt[.(good_rois)]

dt[,activity_filt:=filter(activity, rep(1, 601)) , by=key(dt)]
#
ggplot(data = dt, aes(x=t, y=activity, colour=as.factor(roi_id))) + geom_line()

tp <- dt[,list(activity=mean(activity)) , by=c("treatment","t")]
ggplot(data = tp, aes(x=t, y=activity, colour=as.factor(treatment))) + geom_line()

