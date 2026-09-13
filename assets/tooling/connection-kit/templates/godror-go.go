// Copyright (c) 2026 Oracle and/or its affiliates.
// Connect to Oracle AI Database 26ai with godror.
//   go get github.com/godror/godror
package main

import (
	"database/sql"
	"fmt"

	_ "github.com/godror/godror"
)

func main() {
	dsn := `user="{{USER}}" password="{{PASSWORD}}" connectString="{{HOST}}:{{PORT}}/{{SERVICE}}"`
	db, err := sql.Open("godror", dsn)
	if err != nil {
		panic(err)
	}
	defer db.Close()
	var banner string
	if err := db.QueryRow("SELECT banner FROM v$version WHERE ROWNUM = 1").Scan(&banner); err != nil {
		panic(err)
	}
	fmt.Println(banner)
}
