rm(list=ls())
library(risonno)
library(ggplot2)

FILE <- "/data/validation_out.db"

activity <- function(x,y){
	comp = x + 1i*y
	distance <- c(0, abs(diff(comp)))
	return(distance)
}

files <- list.files(path="./results/rois_t_10s-chunks/", pattern="*.txt", full.names=T)
file_info <- do.call("rbind",strsplit(basename(files), "[_\\.]"))
ref <- as.data.table(file_info[,1:3])	
setnames(ref, colnames(ref),c("roi_id","t","user"))
ref[,roi_id:=as.numeric(roi_id)]
ref[,t:=as.numeric(t)]

annots <- rbindlist(lapply(files, fread))
setnames(annots, colnames(annots),c("behaviour","x","y"))
annots[,behaviour:=ordered(behaviour, levels=c("w","r","g","i"))]
ref <- cbind(ref, annots)

setkeyv(ref, c("roi_id","t"))

ref <- ref[behaviour != 'n', ]

 
files <- list.files(path="./results/rois_t_10s-chunks/", pattern="*.txt", full.names=T)


dt <- loadROIsFromFile(FILE, rois = unique(ref[,roi_id]))
dt[,activity:=activity(x,y) , by=key(dt)]


pos_at_t = dt[t %in% unique(ref[,t]),list(t=t, xt=x, yt=y,roi_id=roi_id)]
setkeyv(pos_at_t,c('roi_id','t'))

setkeyv(ref,c('roi_id','t'))

pdt <- merge(pos_at_t, ref)
pdt[,distance := abs((xt + 1i*yt) - (x +1i*y))]
#todo invert axis -> food?

ggplot(pdt,aes(xt,x)) +
	geom_smooth(method='lm',formula=y~x) +
	geom_point(aes(colour=behaviour, shape=behaviour, size=2, alpha=.5))

mod <- lm(xt ~x, pdt)	
print(summary(mod))

#fixme we are possibly 5s off here
dt_hack = copy(dt)
dt_hack[,t:=t-5]
o = dt_hack[, interpolateROIData(.SD,fs=1/10), by=key(dt)]

act_at_t = o[t %in% unique(ref[,t]),list(t=t, activity=activity,roi_id=roi_id)]
setkeyv(act_at_t,c('roi_id','t'))

pdt2 <- merge(act_at_t, ref)

summary(lm(log10(activity+1e-3) ~ behaviour,pdt2))

#fixme, we also should use max/5%centile/... walked distance -> is it beter than max?!!
