package main

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"os"
	"time"

	go_ora "github.com/sijms/go-ora/v2"
)

func Connect() (*sql.DB, error) {
	dsn := go_ora.BuildUrl(os.Getenv("DB_HOST"), 1521, os.Getenv("DB_SERVICE"),
		os.Getenv("DB_USER"), os.Getenv("DB_PASSWORD"), nil)
	return sql.Open("oracle", dsn)
}

func rowsToArrays(rows *sql.Rows) [][]interface{} {
	cols, _ := rows.Columns()
	out := [][]interface{}{}
	for rows.Next() {
		vals := make([]interface{}, len(cols))
		ptrs := make([]interface{}, len(cols))
		for i := range vals {
			ptrs[i] = &vals[i]
		}
		if err := rows.Scan(ptrs...); err != nil {
			panic(err)
		}
		row := make([]interface{}, len(cols))
		for i, v := range vals {
			switch x := v.(type) {
			case []byte:
				row[i] = string(x)
			case time.Time:
				row[i] = x.Format(time.RFC3339)
			default:
				row[i] = v
			}
		}
		out = append(out, row)
	}
	if out == nil {
		out = [][]interface{}{}
	}
	return out
}

func must(rows *sql.Rows, err error) *sql.Rows {
	if err != nil {
		panic(err)
	}
	return rows
}

func main() {
	db, err := Connect()
	if err != nil {
		panic(err)
	}
	defer db.Close()
	out := map[string][][]interface{}{
		"get_reservation":        rowsToArrays(must(GetReservation(db, 1500))),
		"passenger_reservations": rowsToArrays(must(PassengerReservations(db, 5))),
		"reservations_by_status": rowsToArrays(must(ReservationsByStatus(db, "CONFIRMED"))),
		"reservation_passenger":  rowsToArrays(must(ReservationPassenger(db, 1500))),
	}
	b, _ := json.Marshal(out)
	fmt.Print(string(b))
}

const SQLGetReservation = `SELECT itineraryreservation.reservation_id, itineraryreservation.reservation_status_code, itineraryreservation.ticket_type_code, itineraryreservation.travel_class_code, itineraryreservation.number_in_party
FROM itinerary_reservations itineraryreservation
WHERE itineraryreservation.reservation_id = :b0`

// GetReservation — relational shape
func GetReservation(db *sql.DB, b0 interface{}) (*sql.Rows, error) {
	return db.Query(SQLGetReservation, sql.Named("b0", b0))
}

const SQLPassengerReservations = `SELECT itineraryreservation.reservation_id, itineraryreservation.reservation_status_code
FROM itinerary_reservations itineraryreservation
WHERE itineraryreservation.passenger_id = :b0
ORDER BY itineraryreservation.reservation_id ASC`

// PassengerReservations — relational shape
func PassengerReservations(db *sql.DB, b0 interface{}) (*sql.Rows, error) {
	return db.Query(SQLPassengerReservations, sql.Named("b0", b0))
}

const SQLReservationsByStatus = `SELECT itineraryreservation.reservation_id, itineraryreservation.passenger_id
FROM itinerary_reservations itineraryreservation
WHERE itineraryreservation.reservation_status_code = :b0
ORDER BY itineraryreservation.reservation_id ASC
FETCH FIRST 20 ROWS ONLY`

// ReservationsByStatus — relational shape
func ReservationsByStatus(db *sql.DB, b0 interface{}) (*sql.Rows, error) {
	return db.Query(SQLReservationsByStatus, sql.Named("b0", b0))
}

const SQLReservationPassenger = `SELECT itineraryreservation.reservation_id, passenger.last_name, passenger.email_address
FROM itinerary_reservations itineraryreservation
JOIN passengers passenger ON itineraryreservation.passenger_id = passenger.passenger_id
WHERE itineraryreservation.reservation_id = :b0`

// ReservationPassenger — relational shape
func ReservationPassenger(db *sql.DB, b0 interface{}) (*sql.Rows, error) {
	return db.Query(SQLReservationPassenger, sql.Named("b0", b0))
}
