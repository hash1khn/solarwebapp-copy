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


def add_recurring_bookings(client_id, worker_ids, start_date, time_slot, status, recurrence, recurrence_period):
    current_date = datetime.strptime(start_date, '%Y-%m-%d').date()
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
        end_date = current_date + relativedelta(months=recurrence_period)

        while current_date <= end_date:
            if len(worker_ids) == 0 or len(worker_ids) == 1:
                # Find the nearest available worker for the current date
                client = Client.query.get(client_id)
                workers = Worker.query.all()
                closest_worker = None
                min_distance = float('inf')
                client_lat, client_lon = client.latitude, client.longitude
                day_index = get_day_index(current_date.strftime('%Y-%m-%d'))
                slot_index = get_slot_index(time_slot)

                if slot_index is None:
                    print(f"Invalid time slot for date: {current_date}")
                    break

                for worker in workers:
                    if worker.availability[day_index][slot_index]:
                        distance = haversine(client_lat, client_lon, worker.latitude, worker.longitude)
                        if distance < min_distance:
                            min_distance = distance
                            closest_worker = worker

                if closest_worker:
                    worker_ids = [closest_worker.id]
                else:
                    print(f"No available workers found for the selected time slot on date: {current_date}")
                    break

            for worker_id in worker_ids:
                worker = Worker.query.get(worker_id)
                if not worker:
                    continue

                # Check if a booking already exists
                existing_booking = Booking.query.filter_by(
                    client_id=client_id,
                    worker_id=worker_id,
                    date=current_date,
                    time_slot=time_slot
                ).first()

                if existing_booking:
                    print(f"Booking already exists for date: {current_date} and time_slot: {time_slot} for worker_id {worker_id}")
                else:
                    new_booking = Booking(
                        client_id=client_id,
                        worker_id=worker_id,
                        date=current_date,
                        time_slot=time_slot,
                        status=status,
                        recurrence=recurrence,
                        recurrence_period=recurrence_period  # Save the recurrence period
                    )
                    db.session.add(new_booking)

            current_date += timedelta(days=interval)

        db.session.commit()


@booking_bp.route('/create-booking', methods=['POST'])
@jwt_required()
def create_booking():
    data = request.get_json()
    if not all(key in data for key in ['client_id', 'date', 'time_slot', 'status']):
        return jsonify({'error': 'Bad Request', 'message': 'Missing required fields'}), 400

    client = Client.query.filter_by(id=data['client_id']).first()
    if not client:
        return jsonify({'error': 'Not Found', 'message': 'Client not found'}), 404

    worker_ids = data.get('worker_ids', [])

    # If no worker_ids are provided or only one is provided, find the nearest available worker
    if len(worker_ids) == 0 or len(worker_ids) == 1:
        workers = Worker.query.all()
        closest_worker = None
        min_distance = float('inf')
        client_lat, client_lon = client.latitude, client.longitude
        day_index = get_day_index(data['date'])
        slot_index = get_slot_index(data['time_slot'])

        if slot_index is None:
            return jsonify({'error': 'Bad Request', 'message': 'Invalid time slot'}), 400

        for worker in workers:
            if worker.availability[day_index][slot_index]:
                distance = haversine(client_lat, client_lon, worker.latitude, worker.longitude)
                if distance < min_distance:
                    min_distance = distance
                    closest_worker = worker

        if closest_worker:
            worker_ids = [closest_worker.id]
        else:
            return jsonify({'error': 'Conflict', 'message': 'No available workers found for the selected time slot'}), 409

    booking_instances = []

    for worker_id in worker_ids:
        worker = Worker.query.get(worker_id)
        if not worker:
            return jsonify({'error': 'Not Found', 'message': f'Worker with id {worker_id} not found'}), 404

        # Create booking for each worker
        new_booking = Booking(
            booking_id=data['booking_id'],  # Use the same booking_id for all instances
            client_id=client.id,
            worker_id=worker.id,
            date=datetime.strptime(data['date'], '%Y-%m-%d').date(),
            time_slot=data['time_slot'],
            status=data['status'],
            recurrence=data.get('recurrence'),
            recurrence_period=data.get('recurrence_period')
        )

        # Save each booking instance
        db.session.add(new_booking)
        booking_instances.append(new_booking)
    
    db.session.commit()

    # Return all created booking instances
    return jsonify([booking.to_dict() for booking in booking_instances]), 201


@booking_bp.route('/booking/<int:booking_id>/workers', methods=['GET'])
def get_workers_by_booking(booking_id):
    workers_query = db.session.query(
        Booking.booking_id,
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

@booking_bp.route('/get-all-bookings', methods=['GET'])
@jwt_required()
def get_all_bookings():
    bookings = Booking.query.all()
    return jsonify([booking.to_dict() for booking in bookings]), 200

@booking_bp.route('/bookings/<int:booking_id>', methods=['GET'])
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

@booking_bp.route('/get-booking-by-id/<int:booking_id>', methods=['GET'])
@jwt_required()
def get_booking_by_id(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    return jsonify(booking.to_dict()), 200


@booking_bp.route('/update-booking/<int:booking_id>', methods=['PUT'])
@jwt_required()
def update_booking(booking_id):
    data = request.get_json()
    if not all(key in data for key in ['client_id', 'worker_id', 'date', 'time_slot', 'status']):
        return jsonify({'error': 'Bad Request', 'message': 'Missing required fields'}), 400

    booking = Booking.query.get_or_404(booking_id)

    # Define new_slot_index based on the time_slot provided in the request
    new_slot_index = get_slot_index(data['time_slot'])
    if new_slot_index is None:
        return jsonify({'error': 'Bad Request', 'message': 'Invalid time slot'}), 400

    # Update client_id if it has changed
    if booking.client_id != data['client_id']:
        booking.client_id = data['client_id']

    # Update worker_id if it has changed and handle availability
    if booking.worker_id != data['worker_id']:
        # Mark old availability as true
        old_day_index = get_day_index(booking.date.strftime('%Y-%m-%d'))
        old_slot_index = get_slot_index(booking.time_slot)
        old_worker = Worker.query.get(booking.worker_id)
        if old_worker:
            old_worker.availability[old_day_index][old_slot_index] = True

        # Mark new availability as false
        new_day_index = get_day_index(data['date'])
        new_worker = Worker.query.get(data['worker_id'])
        if new_worker:
            new_worker.availability[new_day_index][new_slot_index] = False

        booking.worker_id = data['worker_id']

    # Update date if it has changed
    if booking.date != datetime.strptime(data['date'], '%Y-%m-%d').date():
        booking.date = datetime.strptime(data['date'], '%Y-%m-%d').date()

    # Update time_slot if it has changed
    if booking.time_slot != data['time_slot']:
        # Mark old availability as true
        old_day_index = get_day_index(booking.date.strftime('%Y-%m-%d'))
        old_slot_index = get_slot_index(booking.time_slot)
        old_worker = Worker.query.get(booking.worker_id)
        if old_worker:
            old_worker.availability[old_day_index][old_slot_index] = True

        # Mark new availability as false
        new_day_index = get_day_index(data['date'])
        new_worker = Worker.query.get(data['worker_id'])
        if new_worker:
            new_worker.availability[new_day_index][new_slot_index] = False

        booking.time_slot = data['time_slot']

    # Update status if it has changed
    if booking.status != data['status']:
        booking.status = data['status']

    # Update recurrence if it has changed
    if booking.recurrence != data.get('recurrence'):
        booking.recurrence = data.get('recurrence')
    
    # Update recurrence_period if it has changed
    if 'recurrence_period' in data:
        booking.recurrence_period = data['recurrence_period']


    db.session.commit()
    return jsonify(booking.to_dict()), 200




@booking_bp.route('/delete-booking/<int:booking_id>', methods=['DELETE'])
@jwt_required()
def delete_booking(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    # Mark availability as true
    worker = Worker.query.get(booking.worker_id)
    day_index = get_day_index(booking.date.strftime('%Y-%m-%d'))

    slot_index = get_slot_index(booking.time_slot)

    if slot_index is None:
        return jsonify({'error': 'Internal Server Error', 'message': 'Invalid time slot'}), 500

    worker.availability[day_index][slot_index] = True

    db.session.delete(booking)
    db.session.commit()
    return jsonify({'message': 'Booking deleted successfully'}), 200

@booking_bp.route('/delete-all-bookings', methods=['DELETE'])
@jwt_required()
def delete_all_bookings():
    try:
        # Delete all records from the Booking table
        num_deleted = db.session.query(Booking).delete()

        db.session.commit()

        return jsonify({'message': f'All bookings have been deleted successfully. Total deleted: {num_deleted}'}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': 'Internal Server Error', 'message': str(e)}), 500
