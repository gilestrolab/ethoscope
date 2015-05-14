rm(list=ls())
library(risonno)
library(ggplot2)

pdf("/tmp/valitation.pdf",w=10,h=5.625)
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


sink("/tmp/annotation_occurence.txt")
print(xtabs( ~  behaviour, ref))
sink()
map <- data.frame(path=FILE, roi_id = unique(ref[,roi_id]))
dt <- loadPsvData(map, FUN=sleepAnalysis)




pos_at_t = dt[t %in% unique(ref[,t]),list(t=t, xt=x, yt=y,
		roi_id=roi_id,activity=activity,ar_diff = ar_diff,
		phi_diff=phi_diff,
		max_velocity=max_velocity)
		]
		
setkeyv(pos_at_t,c('roi_id','t'))

setkeyv(ref,c('roi_id','t'))


pdt <- merge(pos_at_t, ref)
pdt[,distance := abs((xt + 1i*yt) - (x +1i*y))]
#todo invert axis -> food?


pl <- ggplot(pdt,aes(xt,x)) +
	geom_point(aes(colour=behaviour, shape=behaviour, size=1.5, alpha=.5))+
	labs(title= "Relationship between ground-truth(gt)\nand inferred(inf) X positions",x=expression(X[inf] (relative_unit)), y=expression(X[gt] (relative_unit)))
print(pl)

pl <- ggplot(pdt,aes(xt,x)) +
	geom_smooth(method='lm',formula=y~x) +
	geom_point(aes(colour=behaviour, shape=behaviour, size=1.5, alpha=.5))+
	labs(title= "Relationship between ground-truth(gt)\nand inferred(inf) X positions",x=expression(X[inf] (relative_unit)), y=expression(X[gt] (relative_unit)))
	
print(pl)

mod <- lm(xt ~x, pdt)	
print(summary(mod))


pl <- ggplot(pdt,aes(behaviour,activity,fill=behaviour)) +
		geom_boxplot()  +  geom_hline(aes(yintercept=0.03)) +  scale_y_sqrt()
print(pl)

pl <- ggplot(pdt,aes(behaviour,ar_diff,fill=behaviour)) +
		geom_boxplot()  +  scale_y_sqrt()
print(pl)

pl <- ggplot(pdt,aes(behaviour,phi_diff,fill=behaviour)) +
		geom_boxplot()  +  geom_hline(aes(yintercept=0.03)) +  scale_y_sqrt()
print(pl)

pl <- ggplot(pdt,aes(behaviour,max_velocity,fill=behaviour)) +
		geom_boxplot()  +  geom_hline(aes(yintercept=0.006)) +  scale_y_sqrt()
print(pl)																

pl <- ggplot(pdt,aes(ar_diff,activity,shape=behaviour,colour=behaviour)) +
		geom_point() + scale_y_sqrt() + scale_x_sqrt()
print(pl)

#'mod2 <- lm(sqrt(activity) ~ behaviour,pdt2)
#'print(summary(mod2))

data <- dt[roi_id==2, list(colour=asleep,t=t/3600,x=x)]
data <- data[t>5 &  t<10]
pl <- ggplot(data) + geom_line(aes(t,x),colour=2+2*as.numeric(data$colour)) +
		geom_hline(aes(yintercept=0.5),colour="blue",size=2,linetype=2)+
		labs(title= "X plosition vs. time.\n Showing sleeping and active behaviours.",x="t (h)", y="X position (relative unit)")
print(pl)


sub_data <- data[t>7 &  t<7.25]
pl <- ggplot(sub_data) + geom_line(aes(t,x),colour=2+2*as.numeric(sub_data$colour)) +
		geom_hline(aes(yintercept=0.5),colour="blue",size=2,linetype=2)+
		labs(title= "X plosition vs. time.\n Showing sleeping and active behaviours.",x="t (h)", y="X position (relative unit)")
print(pl)

sub_data <- data[t>7.90 &  t<8.15]
pl <- ggplot(sub_data) + geom_line(aes(t,x),colour=2+2*as.numeric(sub_data$colour)) +
		geom_hline(aes(yintercept=0.5),colour="blue",size=2,linetype=2)+
		labs(title= "X plosition vs. time.\n Showing sleeping and active behaviours.",x="t (h)", y="X position (relative unit)")
print(pl)

dev.off()


