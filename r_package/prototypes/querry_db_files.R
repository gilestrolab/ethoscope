
result_dir <- "/data/psv_results/"
all_db_files <- list.files(result_dir,recursive=T, pattern="*.db")


files_info <- do.call("rbind",strsplit(all_db_files,"/"))
files_info <- as.data.table(files_info)
setnames(files_info, c("machine_id", "machine_name", "date","file"))
files_info[,date:=as.POSIXct(date, "%Y-%m-%d_%H-%M-%S", tz="GMT")]
files_info[,path := all_db_files]
