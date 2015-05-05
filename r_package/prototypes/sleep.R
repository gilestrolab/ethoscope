
rm(list=ls())
library(risonno)
library(data.table)
library(ggplot2)

sampling_period <- 10#s
ACTIV_THR <- 0.03

path <- "/data/psv_results/00016dfce6e94dee9bb1a845281b086e/GGSM-001/2015-04-17_17-06-49/2015-04-17_17-06-49_00016dfce6e94dee9bb1a845281b086e.db"
dt <- loadROIsFromFile(path, rois=c(2:15,17:31), reference_hour = 9,FUN=interpolateROIData,fs=2)


dt$h <- NULL
dt$w <- NULL
dt$phi <- NULL
dt$is_inferred <- NULL




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

dt[,activity:=activity(x,y) , by=key(dt)]

dt10s <- copy(dt)


dt10s[, t_round := sampling_period * round(t /sampling_period)]
dt10s[, activity,by=c("t", key(dt))]
dt10s <- dt10s[, list(activity=sum(activity)),by=c("t_round", key(dt))]
setkeyv(dt10s, key(dt))
dt10s[,moving := ifelse(activity > ACTIV_THR, TRUE, FALSE)]
dt10s[,asleep := sleep_contiguous(moving,1/10), by=key(dt10s)]


dt10s[, t_round2 := 600 * round(t_round /600)]
pdt10min <- dt10s[,list(
		slp=mean(asleep),
		slp_sd=sd(asleep),
		moving=mean(moving),
		moving_sd=sd(moving),
		activity=mean(activity),
		activity_sd=sd(activity))
		
		,by=c("t_round2")]

pdt10min[,day:=t_round2/(3600*24),]

#~ pdt10min[,ld := ifelse(day %% 24 < 12, "L","D")]

d <- seq(from=0,to=6.5,by=.5)
rects <- data.frame(xstart = d, xend = d+.5, col = ordered(c("l","d"),levels=c("l","d")))

ggrect <- geom_rect(data = rects, aes(xmin = xstart, xmax = xend, ymin = -Inf, ymax = Inf, fill = col), alpha = 0.4)

pdf("/tmp/sleep.pdf",w=16,h=9)

p <- ggplot() + ggrect+
	geom_line(data=pdt10min, aes(day, slp)) 
print(p)
p <- ggplot() + ggrect+
	geom_line(data=pdt10min, aes(day, moving))
	
print(p)
p <- ggplot() + ggrect +
	geom_line(data=pdt10min, aes(day, activity)) +  geom_hline(aes(yintercept=0.03)) #+ # +  scale_y_sqrt()
#~ 	geom_ribbon(data=pdt10min, aes(day, activity,ymax = (activity + activity_sd), ymin=(activity)))
print(p)
dev.off()

#~ rle_dt <- dt10s[,rle(!moving),by=roi_id]
#~ rle_dt[,immob := !values]
#~ rle_dt[,long_enough := lengths > 5*6]
#~ xtabs(~ immob + long_enough,rle_dt)

