
experiements <- list(
	data.table(path="001", condition="food_both_side", roi_id= 1:32, rep(c("young", "old"),each=16)),
	data.table(path="002", roi_id= 1:32, rep(c("young", "old"),each=16)),
	data.table(path="003", roi_id= 1:32, rep(c("old","young"),each=16)),
	data.table(path="003", roi_id= 1:32, rep(c("old","young"),each=16))
	)
	
master_table <- rbindlist(experiements)
