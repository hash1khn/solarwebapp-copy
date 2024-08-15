# app/routes/booking.py
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from ..models.bookingModel import Booking
from ..models.clientModel import Client
from ..models.workerModel import Worker
from .. import db
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from ..utils import haversine, get_coordinates
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from collections import defaultdict


booking_bp = Blueprint('booking_bp', __name__, url_prefix='/api/bookings')


def get_day_index(date_str):
    date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
    return date_obj.weekday()  # Monday is 0 and Sunday is 6


def get_slot_index(time_slot):
    slots = {
        "09:00-11:00": 0,
        "11:00-13:00": 1,
        "13:00-15:00": 2,
        "15:00-17:00": 3,
        "17:00-19:00": 4
    }

    print(f"Received time_slot: {time_slot}, Type: {type(time_slot)}")
    return slots.get(time_slot)


# def add_recurring_bookings(client_id, worker_id, start_date, time_slot, status, recurrence, recurrence_period):
#     current_date = datetime.strptime(start_date, '%Y-%m-%d').date()
#     recurrence_days = {
#         'daily': 1,
#         'weekly': 7,
#         'biweekly': 14,
#         'monthly': 30,
#         'ten': 10,  # Added ten days option
#         'twenty': 20  # Added twenty days option
#     }

#     if recurrence in recurrence_days:
#         interval = recurrence_days[recurrence]
#         end_date = current_date + relativedelta(months=recurrence_period)

#         print(f"Start Date: {current_date}")
#         print(f"End Date: {end_date}")
#         print(f"Recurrence Interval (days): {interval}")

#         while current_date <= end_date:
#             print(f"Current Date: {current_date}, End Date: {end_date}")
#             print(f"Checking availability for date: {current_date} and time_slot: {time_slot}")
#             day_index = get_day_index(current_date.strftime('%Y-%m-%d'))
#             slot_index = get_slot_index(time_slot)
#             print(f"Day index: {day_index}, Slot index: {slot_index}")

#             worker = Worker.query.get(worker_id)  # Fetch fresh instance
#             print(f"Worker availability before booking: {worker.availability}")

#             # Check if a booking already exists
#             existing_booking = Booking.query.filter_by(
#                 client_id=client_id,
#                 worker_id=worker_id,
#                 date=current_date,
#                 time_slot=time_slot
#             ).first()

#             if existing_booking:
#                 print(f"Booking already exists for date: {current_date} and time_slot: {time_slot}")
#             elif worker and worker.availability[day_index][slot_index]:
#                 new_booking = Booking(
#                     client_id=client_id,
#                     worker_id=worker_id,
#                     date=current_date,
#                     time_slot=time_slot,
#                     status=status,
#                     recurrence=recurrence,
#                     recurrence_period=recurrence_period  # Save the recurrence period
#                 )
#                 worker.availability[day_index][slot_index] = False
#                 db.session.add(worker)
#                 db.session.add(new_booking)
#                 db.session.commit()  # Commit after each addition
#                 print(f"Booking added for date: {current_date} and time_slot: {time_slot}")
#                 print(f"Worker availability after booking: {worker.availability}")
#             else:
#                 print(f"Worker not available on date: {current_date} and time_slot: {time_slot}")

#             current_date += timedelta(days=interval)
#             # Ensure the loop stops if the next current_date exceeds end_date
#             if current_date > end_date:
#                 print(f"Reached the end date: {end_date}. Stopping further bookings.")
#                 break
def calculate_next_date(current_date, recurrence, recurrence_period):
    recurrence_days = {
        'daily': 1,
        'weekly': 7,
        'biweekly': 14,
        'monthly': 30,
        'ten': 10,  # Added ten days option
        'twenty': 20  # Added twenty days option
    }
    
    if recurrence in recurrence_days:
        interval = recurrence_days[recurrence]
        next_date = current_date + timedelta(days=interval * recurrence_period)
        return next_date

    return current_date

def update_worker_availability(worker, date_str, time_slot):
    day_index = get_day_index(date_str)
    slot_index = get_slot_index(time_slot)
    
    if worker.availability[day_index][slot_index]:
        worker.availability[day_index][slot_index] = False
        db.session.add(worker)
        db.session.commit()
        print(f"Updated availability for worker {worker.id} on {date_str} at {time_slot}: {worker.availability}")
    else:
        print(f"Worker {worker.id} is already booked on {date_str} at {time_slot}.")
def generate_unique_booking_id(last_booking_id=None):
    # Generate a unique booking_id based on a sequence
    if last_booking_id is not None:
        return last_booking_id + 1
    last_booking = Booking.query.order_by(Booking.booking_id.desc()).first()
    if last_booking:
        return last_booking.booking_id + 1
    else:
        return 1001 # Increment to generate the next unique booking_id
 # A simple method to generate a booking ID
def find_nearest_worker(client_location, available_workers):
    nearest_worker = None
    shortest_distance = None

    client_lat, client_lon = client_location

    for worker in available_workers:
        worker_lat = worker.latitude
        worker_lon = worker.longitude
        distance = haversine(client_lat, client_lon, worker_lat, worker_lon)

        if shortest_distance is None or distance < shortest_distance:
            shortest_distance = distance
            nearest_worker = worker

    return nearest_worker
 
@booking_bp.route('/create-booking', methods=['POST'])
@jwt_required()
def create_booking():
    data = request.get_json()

    # Validate the required fields
    if not all(key in data for key in ['client_id', 'date', 'time_slot', 'status']):
        return jsonify({'error': 'Bad Request', 'message': 'Missing required fields'}), 400

    client = Client.query.filter_by(id=data['client_id']).first()
    if not client:
        return jsonify({'error': 'Not Found', 'message': 'Client not found'}), 404

    client_location = (client.latitude, client.longitude)

    # Generate a unique booking_id to be shared among all worker bookings
    booking_id = generate_unique_booking_id()

    # If worker_ids are provided, use them; otherwise, find the nearest worker
    worker_ids = data.get('worker_ids')
    if not worker_ids:
        # Find all available workers for the given time slot and date
        available_workers = Worker.query.all()
        nearest_worker = find_nearest_worker(client_location, available_workers)

        if not nearest_worker:
            return jsonify({'error': 'Not Found', 'message': 'No available workers found'}), 404

        worker_ids = [nearest_worker.id]

    booking_instances = []
    for recurrence_count in range(data.get('recurrence_period', 1)):
        if recurrence_count > 0:
            # Increment booking_id for each recurrence
            booking_id = generate_unique_booking_id(booking_id)

        current_date = calculate_next_date(datetime.strptime(data['date'], '%Y-%m-%d').date(), data['recurrence'], recurrence_count)

        for worker_id in worker_ids:
            worker = Worker.query.get(worker_id)
            if not worker:
                return jsonify({'error': 'Not Found', 'message': f'Worker with id {worker_id} not found'}), 404

            # Create the booking
            new_booking = Booking(
                booking_id=booking_id,  # Use the same booking_id for all workers
                client_id=client.id,
                worker_id=worker.id,
                date=current_date,
                time_slot=data['time_slot'],
                status=data['status'],
                recurrence=data.get('recurrence'),
                recurrence_period=data.get('recurrence_period')
            )

            # Update worker availability
            day_index = get_day_index(current_date.strftime('%Y-%m-%d'))
            slot_index = get_slot_index(data['time_slot'])
            if worker.availability[day_index][slot_index]:
                worker.availability[day_index][slot_index] = False

            db.session.add(new_booking)
            db.session.add(worker)
            booking_instances.append(new_booking)

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        return jsonify({'error': 'Database Error', 'message': str(e)}), 500

    return jsonify([booking.to_dict() for booking in booking_instances]), 201


#to get only workers with same booking_id (for editing and searching)
@booking_bp.route('/<int:booking_id>/workers', methods=['GET'])
def get_workers_by_booking(booking_id):
    workers_query = db.session.query(
        Booking.booking_instance_id,
        Worker.id,
        Worker.name,
        Worker.latitude,
        Worker.longitude,
        Worker.area,
        Worker.availability
    ).join(Worker, Booking.worker_id == Worker.id).filter(Booking.booking_id == booking_id).all()

    workers_list = []
    for booking_instance_id, worker_id, worker_name, worker_latitude, worker_longitude, worker_area, worker_availability in workers_query:
        workers_list.append({
            'booking_id': booking_id,  # Include booking_id in the response
            'booking_instance_id': booking_instance_id,
            'worker': {
                'id': worker_id,
                'name': worker_name,
                'latitude': worker_latitude,
                'longitude': worker_longitude,
                'area': worker_area,
                'availability': worker_availability
            }
        })
    
    return jsonify(workers_list), 200

# get all bookings
@booking_bp.route('/get-all-bookings', methods=['GET'])
@jwt_required()
def get_all_bookings():
    bookings = Booking.query.all()
    return jsonify([booking.to_dict() for booking in bookings]), 200

#to send other details for editing and searching()
@booking_bp.route('/get-booking-details/<int:booking_id>', methods=['GET'])
def get_booking_details(booking_id):
    booking = Booking.query.filter_by(booking_id=booking_id).first()
    if not booking:
        return jsonify({'error': 'Not Found', 'message': 'Booking not found'}), 404

    booking_details = {
        'booking_id': booking.booking_id,
        'booking_instance_id': booking.booking_instance_id,
        'client_id': booking.client_id,
        'client': booking.client.to_dict(),  # Assuming Client has a `to_dict` method
        'date': booking.date.strftime('%Y-%m-%d'),
        'time_slot': booking.time_slot,
        'status': booking.status,
        'recurrence': booking.recurrence,
        'recurrence_period': booking.recurrence_period,
    }

    return jsonify(booking_details), 200

# get booking details by booking_id
@booking_bp.route('/get-booking-by-id/<int:booking_id>', methods=['GET'])
@jwt_required()
def get_booking_by_id(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    return jsonify(booking.to_dict()), 200

@booking_bp.route('/update-booking/<int:booking_id>', methods=['PUT'])
@jwt_required()
def update_booking(booking_id):
    data = request.get_json()

    # Fetch the booking instances by booking_id
    existing_bookings = Booking.query.filter_by(booking_id=booking_id).all()

    if not existing_bookings:
        return jsonify({'error': 'Not Found', 'message': 'Booking not found'}), 404

    new_worker_ids = data['worker_ids']
    current_worker_count = len(existing_bookings)
    new_worker_count = len(new_worker_ids)

    # Handle removing workers
    if new_worker_count < current_worker_count:
        # Remove excess bookings and update availability
        for i in range(new_worker_count, current_worker_count):
            booking_to_remove = existing_bookings.pop(i)
            worker_to_update = Worker.query.get(booking_to_remove.worker_id)
            if worker_to_update:
                day_index = get_day_index(data['date'])
                slot_index = get_slot_index(data['time_slot'])
                worker_to_update.availability[day_index][slot_index] = True  # Set availability back to true
                db.session.delete(booking_to_remove)
                db.session.add(worker_to_update)

    # Handle adding new workers
    elif new_worker_count > current_worker_count:
        for i in range(current_worker_count, new_worker_count):
            worker_id = new_worker_ids[i]
            worker = Worker.query.get(worker_id)
            if not worker:
                return jsonify({'error': 'Not Found', 'message': f'Worker with id {worker_id} not found'}), 404

            # Check worker availability
            day_index = get_day_index(data['date'])
            slot_index = get_slot_index(data['time_slot'])
            if not worker.availability[day_index][slot_index]:
                return jsonify({'error': 'Worker Unavailable', 'message': f'Worker with id {worker_id} is not available for the selected date and time'}), 400

            # Create a new booking for the additional worker
            new_booking = Booking(
                booking_id=booking_id,  # Use the same booking_id for all workers
                client_id=existing_bookings[0].client_id,  # Assuming client_id remains the same
                worker_id=worker_id,
                date=datetime.strptime(data['date'], '%Y-%m-%d').date(),
                time_slot=data['time_slot'],
                status=data['status'],
                recurrence=data.get('recurrence', existing_bookings[0].recurrence),
                recurrence_period=data.get('recurrence_period', existing_bookings[0].recurrence_period)
            )

            # Update worker availability
            worker.availability[day_index][slot_index] = False

            db.session.add(new_booking)
            db.session.add(worker)
            existing_bookings.append(new_booking)

    # Update existing bookings
    for i, booking in enumerate(existing_bookings):
        booking.date = datetime.strptime(data['date'], '%Y-%m-%d').date()
        booking.time_slot = data['time_slot']
        booking.status = data['status']
        booking.recurrence = data.get('recurrence', booking.recurrence)
        booking.recurrence_period = data.get('recurrence_period', booking.recurrence_period)

        worker_id = new_worker_ids[i]
        worker = Worker.query.get(worker_id)
        if not worker:
            return jsonify({'error': 'Not Found', 'message': f'Worker with id {worker_id} not found'}), 404

        booking.worker_id = worker.id

        # Update worker availability
        day_index = get_day_index(data['date'])
        slot_index = get_slot_index(data['time_slot'])
        if worker.availability[day_index][slot_index]:
            worker.availability[day_index][slot_index] = False

        db.session.add(worker)
        db.session.add(booking)

    try:
        db.session.commit()
        return jsonify({'message': 'Booking updated successfully'}), 200
    except SQLAlchemyError as e:
        db.session.rollback()
        return jsonify({'error': 'Database Error', 'message': str(e)}), 500


#get all bookings instances
@booking_bp.route('/all-instances', methods=['GET'])
def get_all_booking_instances():
    bookings = Booking.query.all()

    if not bookings:
        return jsonify({'error': 'Not Found', 'message': 'No bookings found'}), 404

    bookings_list = [booking.to_dict() for booking in bookings]
    
    return jsonify(bookings_list), 200

#to get all bookings with the same booking_id
@booking_bp.route('/<int:booking_id>', methods=['GET'])
def get_bookings_by_booking_id(booking_id):
    bookings = Booking.query.filter_by(booking_id=booking_id).all()

    if not bookings:
        return jsonify({'error': 'Not Found', 'message': 'No bookings found with the given booking ID'}), 404

    bookings_list = [booking.to_dict() for booking in bookings]
    
    return jsonify(bookings_list), 200

#to get by booking instance id
@booking_bp.route('/instance/<int:booking_instance_id>', methods=['GET'])
def get_bookings_by_instance_id(booking_instance_id):
    bookings = Booking.query.filter_by(booking_instance_id=booking_instance_id).all()

    if not bookings:
        return jsonify({'error': 'Not Found', 'message': 'No bookings found with the given instance ID'}), 404

    bookings_list = [booking.to_dict() for booking in bookings]
    
    return jsonify(bookings_list), 200

#manipulated json format sending(aawaiz)
@booking_bp.route('/all-booking-details', methods=['GET'])
def get_all_booking_details():
    all_bookings = Booking.query.all()

    if not all_bookings:
        return jsonify({'error': 'Not Found', 'message': 'No bookings found'}), 404

    bookings_response = defaultdict(lambda: {
        "client": {},
        "booking_id": None,
        "date": None,
        "time_slot": None,
        "status": None,
        "recurrence": None,
        "recurrence_period": None,
        "workers": []
    })

    for booking in all_bookings:
        booking_id = booking.booking_id

        # If the client info hasn't been added yet, add it
        if not bookings_response[booking_id]['client']:
            client = booking.client
            bookings_response[booking_id]['client'] = {
                "id": client.id,
                "name": client.name,
                "address": client.address,
                "area": client.area,
                "charge_per_clean": client.charge_per_clean,
                "contact_details": client.contact_details,
                "latitude": client.latitude,
                "longitude": client.longitude,
                "total_panels": client.total_panels
            }

            # Add the booking-level information
            bookings_response[booking_id]["booking_id"] = booking.booking_id
            bookings_response[booking_id]["date"] = booking.date.strftime('%Y-%m-%d')
            bookings_response[booking_id]["time_slot"] = booking.time_slot
            bookings_response[booking_id]["status"] = booking.status
            bookings_response[booking_id]["recurrence"] = booking.recurrence
            bookings_response[booking_id]["recurrence_period"] = booking.recurrence_period

        # Add the worker details
        worker = Worker.query.get(booking.worker_id)
        if worker:
            worker_detail = {
                "id": worker.id,
                "name": worker.name,
                "area": worker.area,
                "latitude": worker.latitude,
                "longitude": worker.longitude,
                "availability": worker.availability
            }
            if worker_detail not in bookings_response[booking_id]["workers"]:
                bookings_response[booking_id]["workers"].append(worker_detail)

    # Convert defaultdict to a list
    bookings_response_list = list(bookings_response.values())

    return jsonify(bookings_response_list), 200

@booking_bp.route('/delete-booking/<int:booking_id>', methods=['DELETE'])
@jwt_required()
def delete_booking(booking_id):
    try:
        # Fetch all booking instances with the provided booking_id
        bookings = Booking.query.filter_by(booking_id=booking_id).all()
        if not bookings:
            return jsonify({'error': 'Not Found', 'message': f'No bookings found with booking ID {booking_id}'}), 404

        # Update the worker's availability before deleting the bookings
        for booking in bookings:
            worker = Worker.query.get(booking.worker_id)
            if worker:
                day_index = get_day_index(booking.date.strftime('%Y-%m-%d'))
                slot_index = get_slot_index(booking.time_slot)
                worker.availability[day_index][slot_index] = True
                db.session.add(worker)

        # Delete all the bookings associated with the booking_id
        for booking in bookings:
            db.session.delete(booking)

        # Commit the changes to the database
        db.session.commit()

        return jsonify({'message': f'Bookings with booking ID {booking_id} have been deleted successfully.'}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': 'Internal Server Error', 'message': str(e)}), 500

