rm(list=ls())
library(risonno)
library(ggplot2)
pdf("/tmp/sex_effect.pdf",w=10,h=5.625)
path <- rep(c("/data/psv_results/00076dfce6e94dee9bb1a845281b086e/GGSM-007/2015-05-08_16-28-08/2015-05-08_16-28-08_00076dfce6e94dee9bb1a845281b086e.db",
			  "/data/psv_results/00086dfce6e94dee9bb1a845281b086e/GGSM-008/2015-05-08_16-30-02/2015-05-08_16-30-02_00086dfce6e94dee9bb1a845281b086e.db"),
			  each=32)

roi_id <- 1:32
sex <- rep(c("female","male"),length.out=16)
sex <- c(sex,rev(sex))
map <- data.table(path,roi_id,sex)


dt <- loadPsvData(map, reference_hour=9.0, FUN=sleepAnalysis)

dt[, t_d:=t/(24*3600)]
dt[, LD := ordered(ifelse(t_d %% 1 < .5, "L","D"),levels=c("L","D"))]


#global visualisation

p <- ggplot(dt,aes(x=t_d,y=sprintf("%s@%s@%02d",sex,file,roi_id),fill=sqrt(activity))) + geom_tile(alpha=1) +
	labs(title= "Overview of individual activity pattern over time",x="time (day)", y="Individual")
print(p)
p <- ggplot(dt,aes(x=t_d,y=sprintf("%s@%s@%02d",sex,file,roi_id),fill=asleep)) + geom_tile() +
	labs(title= "Overview of individual sleep pattern over time",x="time (day)", y="Individual")
	
print(p)
valid_dt <- dt[LD=="L",list(sleep=mean(asleep)), by=.(roi_id,file)][sleep < .9,.(file,roi_id)]
dt <- dt[valid_dt]

{
# 30mins
dt[,t_r := round(t/(60*30)) * 60*30]

dt_per_t <- dt[,list(
			sleep=mean(asleep)),
			by=c("t_r","sex",key(dt))]

dt_per_t <- dt_per_t[,list(
			sleep=mean(sleep),
			sd_sleep=sd(sleep)),
			by=.(t_r,sex)]
			
dt_per_t[,t:=t_r]
dt_per_t[,zg_t:=t %% (3600*24)]

dt_per_zg <- dt_per_t[,list(sleep=mean(sleep),sd_sleep=mean(sd_sleep)),by=.(zg_t,sex)]


p <- ggplot(dt_per_t, aes(t/(3600),sleep,colour=sex)) + geom_line() + geom_ribbon(aes(ymin=sleep-2*sd_sleep/sqrt(32), ymax=sleep+2*sd_sleep/8,fill=sex, colour=NULL,alpha=.1)) +
		labs(title= "Sleep occurrence vs. time,\n for males (N~=30) and females (N~=30)",x="time (h)", y="Average fraction of sleeping flies")
print(p)
p <- ggplot(dt_per_zg, aes(zg_t/(3600),sleep,colour=sex)) + geom_line() + geom_ribbon(aes(ymin=sleep-2*sd_sleep/sqrt(32), ymax=sleep+2*sd_sleep/8,fill=sex, colour=NULL,alpha=.1)) + 
	labs(title= "Sleep occurrence vs. time,\n for males (N~=30) and females (N~=30)",x="Zeitgeber time (h)", y="Average fraction of sleeping flies")
print(p)

}


p <- ggplot(dt[,list(sleep=mean(asleep)), by=.(LD,sex,roi_id,file)], aes(sex, sleep, fill=sex, linetype=LD)) + geom_boxplot()+ 
	labs(title= "Total day and night sleep,\n for males (N~=30) and females (N~=30)", y="Fraction of time spent sleeping")
print(p)
#'ggplot(dt[,list(sleep=mean(asleep)), by=.(LD,sex,roi_id,file)], aes(sex, sleep, alpha=file,fill=sex, linetype=LD)) + geom_boxplot()


dt[,x_rel:=ifelse(roi_id > 16, 1-x,x)]
p <- ggplot(dt[asleep==T,], aes(x_rel, colour=sex)) + geom_density() + 
	labs(title= "Distribution of the position of flies in tubes,\n for males (N~=30) and females (N~=30), while ASLEEP  ", x="Relative position (0 - > 1= outside -> inside)")
print(p)
p <- ggplot(dt[asleep==F,], aes(x_rel, colour=sex)) + geom_density() + 
	labs(title= "Distribution of the position of flies in tubes,\n for males (N~=30) and females (N~=30), while AWAKE  ", x="Relative position (0 - > 1= outside -> inside)")
print(p)
	



boot_dist <- function(dt, i){
	
	uniques <- unique(dt[,.(file,roi_id)])
	idx <- sample(1:nrow(uniques), floor(nrow(uniques)/2))
	to_keep <- uniques[idx]
	
	h <- hist(dt[to_keep,.(sex,x_rel)][sex=="female",x_rel],nclass=100,plot=F)
	dtf <- as.data.table(list(d=h$density, x=h$mids, sex="female"))

	h <- hist(dt[to_keep,.(sex,x_rel)][sex=="male",x_rel],nclass=100,plot=F)
	dtm <- as.data.table(list(d=h$density, x=h$mids, sex="male"))

	out <- rbind(dtm,dtf)
	out[,rep:=i]
	out
}

print("bootstrap")
out <- lapply(1:200, boot_dist,dt=dt)

out <- rbindlist(out)
plt = out[, 
	list(
		mean_d=median(d),
		top_d = quantile(d,probs=(.95)),
		bottom_d = quantile(d,probs=(.05))
	),
	by=.(x,sex)]
	
	

p <- ggplot(plt, aes(x, mean_d,colour=sex, fill=sex)) + geom_line() + geom_ribbon(aes(ymin=bottom_d, ymax=top_d,alpha=.3))
print(p)
# sleep structure


sleepStructure <- function(slp,sampling_period){
	rl_res <- rle(slp)
	sleep_bouts <- rl_res$lengths[rl_res$values]* sampling_period
	
	list(number = length(sleep_bouts)/(length(slp) *sampling_period),
		duration=median(sleep_bouts)
		)
}

#'slp <- dt[file=="2015-05-08_16-28-08_00076dfce6e94dee9bb1a845281b086e.db"& roi_id==2,asleep]
plt <- dt[,sleepStructure(asleep,10),by=c("sex",key(dt))]
# bout duration (min) vs. #bouts(/h)
p <- ggplot(plt, aes(number*3600,duration/60,colour=sex,shape=sex)) + geom_point() + geom_density2d(bins=3) + 
	labs(title= "Sleep structure",x="Number of bouts per hour (/h)", y="Median bout duration (min)")
print(p)
dev.off()
