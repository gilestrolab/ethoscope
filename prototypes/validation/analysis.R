rm(list=ls())
library(risonno)
library(ggplot2)

FILE <- "/data/validation/validation_out.db"
ANNOT_RESULTS <- "/data/validation/rois_t_10s-chunks"
behaviour_map <- list(w="walking", r="spinning", g="grooming", i="immobile")
activity <- function(x,y){
	comp = x + 1i*y
	distance <- c(0, abs(diff(comp)))
	return(distance)
}

files <- list.files(path=ANNOT_RESULTS, pattern="*.txt", full.names=T)
file_info <- do.call("rbind",strsplit(basename(files), "[_\\.]"))
ref <- as.data.table(file_info[,1:3])	
setnames(ref, colnames(ref),c("roi_id","t","user"))
ref[,roi_id:=as.numeric(roi_id)]
ref[,t:=as.numeric(t)]

annots <- rbindlist(lapply(files, fread))
setnames(annots, colnames(annots),c("behaviour","x","y"))
annots[,behaviour:=behaviour_map[behaviour]]
annots[,behaviour:=ordered(behaviour, levels=c("walking","spinning","grooming","immobile"))]
ref <- cbind(ref, annots)

setkeyv(ref, c("roi_id","t"))

ref <- ref[behaviour != 'n', ]

print(xtabs( ~  behaviour, ref))

 
files <- list.files(path="./results/rois_t_10s-chunks/", pattern="*.txt", full.names=T)


dt <- loadROIsFromFile(FILE, rois = unique(ref[,roi_id]))
dt[,activity:=activity(x,y) , by=key(dt)]


pos_at_t = dt[t %in% unique(ref[,t]),list(t=t, xt=x, yt=y,roi_id=roi_id)]
setkeyv(pos_at_t,c('roi_id','t'))

setkeyv(ref,c('roi_id','t'))


pdt <- merge(pos_at_t, ref)
pdt[,distance := abs((xt + 1i*yt) - (x +1i*y))]
#todo invert axis -> food?
pdf("/tmp/valitation.pdf",w=16,h=9)
pl <- ggplot(pdt,aes(xt,x)) +
	geom_smooth(method='lm',formula=y~x) +
	geom_point(aes(colour=behaviour, shape=behaviour, size=2, alpha=.5))

print(pl)
mod <- lm(xt ~x, pdt)	
print(summary(mod))


d = copy(dt)
sampling_period <- 10
d[, t_round := sampling_period * (floor(d[,t] /sampling_period))]
setkey(d, t_round)
o <- d[,list(t0=min(t), tf=max(t),activity=sum(activity)),by=c("t_round","roi_id")]
	
	


act_at_t = o[t_round %in% unique(ref[,t]),list(t=t_round, activity=activity,roi_id=roi_id)]
setkeyv(act_at_t,c('roi_id','t'))

pdt2 <- merge(act_at_t, ref)
pl <- ggplot(pdt2,aes(behaviour,activity,fill=behaviour)) +
		geom_boxplot()  +  geom_hline(aes(yintercept=0.03)) +  scale_y_sqrt()
print(pl)

mod2 <- lm(sqrt(activity) ~ behaviour,pdt2)
print(summary(mod2))


dev.off()
