rm(list=ls())
library(risonno)


result_dir <- "/data/psv_results/"
all_db_files <- list.files(result_dir,recursive=T, pattern="*.db")


files_info <- do.call("rbind",strsplit(all_db_files,"/"))
files_info <- as.data.table(files_info)
setnames(files_info, c("machine_id", "machine_name", "date","file"))
files_info[,date:=as.POSIXct(date, "%Y-%m-%d_%H-%M-%S", tz="GMT")]
files_info[,path := paste0(result_dir,all_db_files)]

setkey(files_info,file)
files <- data.table(file=c(
	"2015-05-06_15-53-09_00016dfce6e94dee9bb1a845281b086e.db",
	"2015-05-06_16-00-17_00026dfce6e94dee9bb1a845281b086e.db",
	"2015-05-06_15-53-33_00036dfce6e94dee9bb1a845281b086e.db",
	"2015-05-06_15-53-46_00046dfce6e94dee9bb1a845281b086e.db"),
	condition = c(
		"food_both_side",
		"cotton_wool",
		"micropore",
		"plastic_tape"),
	 key="file")



experiements <- list(
	data.table( condition="food_both_side", roi_id= 1:32, age=rep(c("young", "old"),each=16)),
	data.table(condition="cotton_wool", roi_id= 1:32, age=rep(c("young", "old"),each=16)),
	data.table(condition="micropore", roi_id= 1:32, age=rep(c("old","young"),each=16)),
	data.table(condition="plastic_tape",roi_id= 1:32, age=rep(c("old","young"),each=16))
	)
experiements <- rbindlist(experiements)


setkey(experiements,"condition")

master_table <- merge(files_info[files], experiements, by="condition")


master_table <- master_table[,.(path, roi_id, condition,age)]


valid_files <- unique(master_table[,path])
master_table <- master_table[ path %in% valid_files]

dt  <- loadPsvData(master_table,FUN=sleepAnalysis,reference_hour=9.0)
#'dt  <- loadPsvData(unique(master_table[,path])[c(1,4)],sleepAnalysis)


m <- dt[,list(average_sleep= mean(asleep),average_movement = mean(moving)),by=key(dt)]
m <- m[average_movement > .1 & average_sleep > .05, ]

m$average_movement <- NULL
m$average_sleep <- NULL

dt <- dt[m]
dt[,x_rel:=ifelse(roi_id > 16, 1-x,x)]
ggplot(dt, aes(x_rel)) + geom_density(aes(group=condition, colour=condition, linetype=condition))
ggplot(dt[condition == "cotton_wool",], aes(x_rel)) + geom_density(aes(group=roi_id, colour=roi_id))

#'ggplot(dt[,list(slp=mean(asleep)),by=c("roi_id","condition")], aes(condition,slp, fill=condition)) + geom_boxplot()



#'

	
dt[, t_r := round(t / (30*60)) * (30*60)]
pdt <- dt[,
	list(asleep=mean(asleep),
			activity=median(activity),
			asleep=mean(asleep)),
	by=c("t_r","condition")
]



geom_ld_plot <- function(t_day){
	d <- seq(from=floor(min(t_day)),to=ceil(max(t_day)),by=.5)

	ld_seq <- ordered(c("l","d"),levels=c("l","d"))
	
	LD <- data.frame(xstart = d, xend = d+.5, LD = rep(ld_seq, length.out=length(d)))
	geom_rect(data = LD, aes(xmin = xstart, xmax = xend, ymin = -Inf, ymax = Inf, fill = LD), alpha = 0.2)
}


#'rects <- data.frame(xstart = d, xend = d+.5, col = ordered(c("l","d"),levels=c("l","d")))
#'
#'ggrect <- geom_rect(data = rects, aes(xmin = xstart, xmax = xend, ymin = -Inf, ymax = Inf, fill = col), alpha = 0.4)
#'
#'pdf("/tmp/sleep.pdf",w=16,h=9)
#'
#'p <- ggplot() + ggrect+
#'	geom_line(data=pdt10min, aes(day, slp)) 
#'print(p)
#'p <- ggplot() + ggrect+
#'	geom_line(data=pdt10min, aes(day, moving))
#'	
#'print(p)
#'p <- ggplot() + ggrect +
#'	geom_line(data=pdt10min, aes(day, activity)) +  geom_hline(aes(yintercept=0.03)) #+ # +  scale_y_sqrt()
#'#~ 	geom_ribbon(data=pdt10min, aes(day, activity,ymax = (activity + activity_sd), ymin=(activity)))
#'print(p)
#'dev.off()



dt[,day:=t/(3600*24)]

ggplot(dt[, list(sleep=mean(asleep)), by=.(condition,roi_id,ld)], aes(condition,sleep,fill=condition,linetype=ld)) + geom_boxplot()

ggplot() + geom_ld_plot(pdt$day) + geom_line(data=pdt, aes(day, activity,colour=condition, linetype=condition))
