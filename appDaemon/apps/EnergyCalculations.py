import appdaemon.plugins.hass.hassapi as hass
from datetime import datetime, timedelta



class EnergyCalculations(hass.Hass):
   vaasa_elektriska_monthly_cost   = 4.00    # Vaasa elektriska monthly subscription cost in euro
   electric_grid_monthly_cost      = 52.11   # Electric grid connection monthly cost in euro

   day_transfer_charge           = 3.87      # Grid transfer cost in cent/kWh from 07 - 22
   night_transfer_charge         = 1.31      # Grid transfer cost in cent/kWh from 22 - 07
   vaasa_elektriska_transfer_charge = 0.41   # Vaasa elektriska pörssisähkö transfer charge in cent/kWh
   electricity_tax      = 2.87               # Electricity tax c/kWh
                                             # Currently not in use

   update_interval_minutes = 1               # How often the energy calculations will be updated

   entity_id_running_energy_costs = "sensor.running_energy_costs"
   entity_id_nordpool_sensor  = "sensor.nordpool_kwh_fi_eur_3_10_024"

   day_transfer_charge_id = "input_number.day_transfer_charge"
   night_transfer_charge_id = "input_number.night_transfer_charge"

   absolute_electricity_price_c_kWh_id = "sensor.electricity_price"
   absolute_electricity_price_E_kWh_id = "sensor.electricity_price_E_kWh"
   mean_electricity_price_c_kWh_id     = "sensor.electricity_price_mean_c_kWh"


   def initialize(self):
      # Calculate the next time to run the function, 1 second past the next full minute
      now = datetime.now()
      next_minute = now + timedelta(minutes=1)
      start_time = next_minute.replace(second=1, microsecond=0)

      self.initialize_all_parameters()

      # Schedule the function to run at 1 second past every new minute
      # self.run_every(self.main_update_routine, "now", 1)
      self.run_every(self.main_update_routine, start_time, self.update_interval_minutes * 60)
      # self.run_minutely(self.main_update_routine, start=start_time)


   def initialize_all_parameters(self):
      # Dynamically create or set default values for input_number entities only if they don't exist
      self.create_input_number(self.day_transfer_charge_id, "Electricity Grid Day Transfer Charge", 3.87, 0.0, 10.0, 0.1)
      self.create_input_number(self.night_transfer_charge_id, "Electricity Grid Night Transfer Charge", 1.31, 0.0, 10.0, 0.1)

      self.listen_event(self.change_state, event = "call_service")

      # Set up state listeners (callbacks) for when these values change
      self.listen_state(self.input_number_changed, self.day_transfer_charge_id)
      self.listen_state(self.input_number_changed, self.night_transfer_charge_id)


   def update_internal_parameters(self):
      # Update our local properties for ease of use
      self.day_transfer_charge = float(self.get_state(self.day_transfer_charge_id))
      self.night_transfer_charge = float(self.get_state(self.night_transfer_charge_id))


   def change_state(self,event_name,data, kwargs):
      entity_id = data["service_data"]["entity_id"]
      new_value = data["service_data"].get("value")

      if entity_id == self.day_transfer_charge_id:
         self.set_state(self.day_transfer_charge_id, state=new_value)

      elif entity_id == self.night_transfer_charge_id:
         self.set_state(self.night_transfer_charge_id, state=new_value)


   def input_number_changed(self, entity, attribute, old, new, kwargs):
      # Log whenever an input_number value changes
      self.log(f"{entity} changed from {old} to {new}")
      
      # Update the internal values after the change
      self.update_internal_parameters()

      # Allow immediate AC state update
      self.last_state_change_time = datetime.now() - timedelta(seconds=self.min_state_change_time+1)


   def create_input_number(self, entity_id, name, initial, min_value, max_value, step):
      # Check if the entity already exists
      entity_state = self.get_state(entity_id)
      # entity_state = None
      
      if entity_state is None:
         # Entity doesn't exist, so create it with the initial value
         self.log(f"Creating {entity_id} with initial value {initial}")
         self.set_state(entity_id, state=initial, attributes={
            "min": min_value,
            "max": max_value,
            "step": step,
            "mode": "slider",
            #"mode": "slider-entity-row",
            "friendly_name": name
         })
      #else:
         # Entity exists, don't overwrite it
         #self.log(f"{entity_id} already exists with value {entity_state}")


   def main_update_routine(self, kwargs):
      self.update_energy_price()
      self.calculate_energy_cost()


   def calculate_energy_cost(self):
      if self.update_interval_minutes != 1:
         self.log(f"### ERROR: update_interval_minutes must be 1 but is {self.update_interval_minutes}. You need to add support for that ###")
         return

      # Fetch current electricity price
      price = self.get_state(self.absolute_electricity_price_c_kWh_id, attribute="state")
      # Fetch total energy use (kWh) up to this point
      current_energy_import = self.get_state("sensor.p1_meter_energy_import", attribute="state")
      
      # Convert to floats if not None (handles missing sensor data)
      if price is not None and current_energy_import is not None:
         price = float(price)
         current_energy_import = float(current_energy_import)
         self.log(f"Current energy value: {current_energy_import}")

         # Get historical energy import value from exactly one minute ago
         last_energy_import = self.get_last_energy_import()
         self.log(f"Last energy value: {last_energy_import}")
         self.log(f"Energy delta: {round(current_energy_import - last_energy_import, 3)}")

         if last_energy_import is not None:
            # Calculate the energy used in the last minute (current - previous)
            energy_used_last_minute = current_energy_import - last_energy_import

            # Calculate the cost for the energy used in the last minute (€/kWh * kWh used)
            cost_last_minute_cents = price * energy_used_last_minute

            # Calculate the cost for monthly expenses used in the last minute
            minutes_in_month = self.calculate_minutes_in_month()
            fixed_interval_cost_cents = (self.vaasa_elektriska_monthly_cost + self.electric_grid_monthly_cost) / minutes_in_month * 100
            self.log(f"Fixed interval cost (vaasa elektriska + grid cost) {round(fixed_interval_cost_cents, 3)} cent")

            # Fetch the current state of the sensor (convert to float, default to 0 if it doesn't exist)
            current_cost_euro = self.get_state(self.entity_id_running_energy_costs)
            if current_cost_euro is None:
               current_cost_euro = 0.0
            else:
               current_cost_euro = float(current_cost_euro)
               
            self.log(f"Current cost: {round(current_cost_euro, 2)}")

            # Add the cost for the last interval
            new_cost_euro = current_cost_euro + (cost_last_minute_cents / 100) + (fixed_interval_cost_cents / 100)

            # Add the monthly cost for the last interval
            
            self.log(f"Energy used last minute: {energy_used_last_minute:.6f} kWh, Price: {price:.6f} c/kWh, Cost: {cost_last_minute_cents:.6f} cents, Total cost: {new_cost_euro} euro")
               
            # Store the cost as an entity in Home Assistant (sensor entity)
            self.set_state(self.entity_id_running_energy_costs, state=new_cost_euro, attributes={
               "unit_of_measurement": "€",
               "friendly_name": "Running Energy Costs",
               "icon": "mdi:currency-eur",
               "state_class": "total_increasing"
            })
         else:
               self.log("No historical data found for the previous minute, skipping calculation.")
      else:
         self.log("Missing data from one or more sensors, skipping this minute.")


   def get_last_energy_import(self):
      # Fetch the historical data for sensor.p1_meter_energy_import exactly one minute ago
      now = datetime.now()
      one_minute_ago = now - timedelta(minutes=1)
      
      history = self.get_history(entity_id="sensor.p1_meter_energy_import", start_time=one_minute_ago, end_time=now)
      # self.log(f"History: {history}")
      
      if history and len(history[0]) > 0:
         # Return the state of the entity at the latest historical entry one minute ago
         return float(history[0][0]['state'])
      else:
         return None


   def update_energy_price(self):
    current_hour = datetime.now().hour
    hourly_prices = self.calculate_hourly_prices()
    price_now = hourly_prices[current_hour]
    mean_price = self.calculate_mean_value(hourly_prices)

    self.set_state(self.absolute_electricity_price_c_kWh_id, state=price_now, attributes={
        "unit_of_measurement": "c/kWh",
        "friendly_name": "Electricity price history"
    })

    self.set_state(self.absolute_electricity_price_E_kWh_id, state=price_now/100, attributes={
        "unit_of_measurement": "E/kWh",
        "friendly_name": "Electricity price history Euro/kWh"
    })

    self.set_state(self.mean_electricity_price_c_kWh_id, state=mean_price, attributes={
        "unit_of_measurement": "c/kWh",
        "friendly_name": "Electricity price mean history Cent/kWh"
    })


   def calculate_hourly_prices(self):
      today = self.get_state(self.entity_id_nordpool_sensor, attribute="today")
      tomorrow_valid = self.get_state(self.entity_id_nordpool_sensor, attribute="tomorrow_valid")
      tomorrow = self.get_state(self.entity_id_nordpool_sensor, attribute="tomorrow")
      if (tomorrow_valid == True):
         hourly_prices = today + tomorrow
      else:
         # Hacky solution to allow calculations any time of the day, even when tomorrow is not available
         # Will probably yield acceptable results for the morning/early day, but can be way off in afternoon/evening
         # The hope is that the next day pricing will have arrived by then
         # self.log(f"No price for tomorrow, using todays prices as estimation for tomorrow")
         hourly_prices = today + today

      # self.log(f"Today+tomorrow base prices {len(hourly_prices)} items: {hourly_prices}")

      # Add the Vaasa Elektriska fixed transfer charge
      for i in range(len(hourly_prices)):
         hourly_prices[i] = hourly_prices[i] + self.vaasa_elektriska_transfer_charge

      # Add the electricity tax
      #for i in range(len(hourly_prices)):
      #   hourly_prices[i] = hourly_prices[i] + self.electricity_tax

      # Add the night / day grid transfer charge
      for i in range(len(hourly_prices)):
         if ( (i % 24) >= 22 or (i % 24) < 7):
            # Night transfer charge
            hourly_prices[i] = hourly_prices[i] + self.night_transfer_charge
         else:
            # Day transfer charge
            hourly_prices[i] = hourly_prices[i] + self.day_transfer_charge

      for i in range(len(hourly_prices)):
         # Safety in case once in a blue moon we get negative prices
         # Setting it to 0 will avoid any strange calculations later on
         # This will have minimal effect in practice and will almost never be applied
         if (hourly_prices[i] < 0):
            hourly_prices[i] = 0

      # Round each price to one decimal place
      hourly_prices = [round(price, 1) for price in hourly_prices]

      return hourly_prices
   

   def calculate_mean_value(self, item_list):
      # Calculate the mean value of the hourly prices
      if item_list:  # Check if the list is not empty
         mean_value = sum(item_list) / len(item_list)
      else:
         mean_value = 0  # or handle empty list case appropriately
      mean_value = round(mean_value, 1)
      return mean_value
   

   def calculate_minutes_in_month(self):
      # Get the current date
      now = datetime.now()

      # Get the first day of the next month
      if now.month == 12:
         next_month = datetime(now.year + 1, 1, 1)
      else:
         next_month = datetime(now.year, now.month + 1, 1)

      # Calculate the number of days in the current month
      days_in_month = (next_month - datetime(now.year, now.month, 1)).days

      # Number of minutes in a day
      minutes_per_day = 24 * 60

      # Calculate total minutes in the current month
      minutes_in_month = days_in_month * minutes_per_day

      return minutes_in_month