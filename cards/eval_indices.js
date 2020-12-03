db = db.getSiblingDB("admin"); 
dbs = db.runCommand({ "listDatabases": 1 }).databases; 
dbs.forEach(function(database) { 
    db = db.getSiblingDB(database.name); 
    db.getCollectionNames().forEach(function(collname) {
        accesses = db[collname].aggregate([{$indexStats:{}}]);
        accesses._batch.forEach(function(index) {
            //printjson(index);
            if (0 == index.accesses.ops) { 
                print("DB: " + database.name + ", Coll: " + collname + ", index: " + index.name + " unused since " + index.accesses.since);
            }
        });
    });
});
