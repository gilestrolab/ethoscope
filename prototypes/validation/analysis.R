#'rm(list=ls())
library(risonno)
library(ggplot2)


FILE <- "/data/validation/validation_out.db"
ANNOT_RESULTS <- "/data/validation/rois_t_10s-chunks"
ANNOT_LEVELS <- c("walking","spinning","micro-mov.","immobile")
BEHAVIOUR_MAP <- list(w="walking", r="spinning", g="micro-mov.", i="immobile")

make_annotation_df <- function(annot_result_dir,behaviour_map,annot_levels){
	files <- list.files(path=annot_result_dir, pattern="*.txt", full.names=T)
	file_info <- do.call("rbind",strsplit(basename(files), "[_\\.]"))
	ref <- as.data.table(file_info[,1:3])	
	setnames(ref, colnames(ref),c("roi_id","t","user"))
	ref[,roi_id:=as.numeric(roi_id)]
	ref[,t:=as.numeric(t)]

	annots <- rbindlist(lapply(files, fread))
	setnames(annots, colnames(annots),c("behaviour","x","y"))
	annots[,behaviour:=behaviour_map[behaviour]]
	annots[,behaviour:=ordered(behaviour, levels=annot_levels)]
	ref <- cbind(ref, annots)

	setkeyv(ref, c("roi_id","t"))

	ref <- ref[behaviour != 'n', ]
	return(ref)
}

ref <- make_annotation_df(ANNOT_RESULTS, BEHAVIOUR_MAP, ANNOT_LEVELS )


sink("./annotation_occurence.txt")
print(xtabs( ~  behaviour, ref))
sink()
map <- data.frame(path=FILE, roi_id = unique(ref[,roi_id]))
dt <- loadPsvData(map, FUN=sleepAnalysis)




pos_at_t = dt[t %in% unique(ref[,t]),list(t=t, xt=x, yt=y,roi_id=roi_id)]
setkeyv(pos_at_t,c('roi_id','t'))

setkeyv(ref,c('roi_id','t'))

stop("boom")

pdt <- merge(pos_at_t, ref)
pdt[,distance := abs((xt + 1i*yt) - (x +1i*y))]
#todo invert axis -> food?
pdf("/tmp/valitation.pdf",w=16,h=9)
#'pl <- ggplot(pdt[behaviour != "walking"],aes(xt,x)) +
pl <- ggplot(pdt,aes(xt,x)) +
	geom_smooth(method='lm',formula=y~x) +
	geom_point(aes(colour=behaviour, shape=behaviour, size=2, alpha=.5))

print(pl)
mod <- lm(xt ~x, pdt)	
print(summary(mod))

o = copy(dt)

#'sampling_period <- 10
#'d[, t_round := sampling_period * (floor(d[,t] /sampling_period))]
#'setkey(d, t_round)
#'
#'
#'o <- d[,list(
#'			t0=min(t), 
#'			tf=max(t),
#'			cvrd_dist=sum(activity),
#'			max_speed=max(activity),
#'			ar_diff=sum(ar_diff),
#'			phi_diff=sum(phi_diff)
#'		),
#'		by=c("t_round","roi_id")]
	
	


act_at_t = o[t %in% unique(ref[,t])]
setnames(act_at_t, c("x","y"),c("xt","yt"))
setkeyv(act_at_t,c('roi_id','t'))

pdt2 <- merge(act_at_t, ref)
pl <- ggplot(pdt2,aes(behaviour,cvrd_dist,fill=behaviour)) +
		geom_boxplot()  +  geom_hline(aes(yintercept=0.03)) +  scale_y_sqrt()

pl <- ggplot(pdt2,aes(behaviour,ar_diff,fill=behaviour)) +
		geom_boxplot()  +  geom_hline(aes(yintercept=0.03)) +  scale_y_sqrt()

pl <- ggplot(pdt2,aes(behaviour,phi_diff,fill=behaviour)) +
		geom_boxplot()  +  geom_hline(aes(yintercept=0.03)) +  scale_y_sqrt()

pl <- ggplot(pdt2,aes(behaviour,max_velocity,fill=behaviour)) +
		geom_boxplot()  +  geom_hline(aes(yintercept=0.006)) +  scale_y_sqrt()
																
ggplot(pdt2,aes(max_velocity,activity,shape=behaviour,colour=behaviour)) +
		geom_point() + scale_y_sqrt() + scale_x_sqrt()
print(pl)

mod2 <- lm(sqrt(activity) ~ behaviour,pdt2)
print(summary(mod2))


dev.off()


