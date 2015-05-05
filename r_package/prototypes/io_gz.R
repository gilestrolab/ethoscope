
loadSampleData <- function(name="",list=F){
	db_file <- system.file("data/db_files.tar.xz", package="risonno")
	
	if(list == T){
		content <- untar(db_file, list=T)
		db_files <- content
		out <- basename(content)[dirname(content) != '.']
		return(out)
		}
	if(name == "")
		stop("INVALID FILE NAME. List available files using `list=TRUE`")
	
	d <- tempdir()
	file_name <- file.path("db_files",name)
	r <- untar(db_file, files=file_name,exdir=d)
	if(r == 2){
		unlink(d, recursive=T)
		stop("INVALID FILE NAME. List available files using `list=TRUE`")
		}
	out <-file.path(d,file_name)
	warning("Do not, forget to unlink file")
}
 loadSampleData("validation")
