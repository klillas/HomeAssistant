import appdaemon.plugins.hass.hassapi as hass
from datetime import datetime, timedelta
import time


#
# AC Controller app
#
# Args:
#

class ACController(hass.Hass):
  target_room_min_temperature = 18    # Minimum room temperature, always turn on AC even during high prices if we go under this
  target_room_temperature     = 23    # Ideal room temperature, try to reach this target under ideal pricing circumstances
  target_room_max_temperature = 24    # Maximum allowed room temperature, do not try to collect more heat even if price is low

  min_mean_price_multiplier = 0.5     # If the current price is lower than this mean multiplier, recommend running AC fulltime
  max_mean_price_multiplier = 1.5     # If the current price is higher than this mean multiplier, recommend shutting down AC

  min_absolute_price        = 5.0     # If the current price is lower than this absolute price, recommend running AC fulltime
  max_absolute_price        = 30.0    # If the current price is higher than this absolute price, recommend shutting down AC

  min_state_change_time         = 1800      # Amount of seconds before another state change is allowed to reduce oscillating behavior
  ignore_change_time_temp_diff  = 2         # We ignore the waiting time between state changes if the temp diff between current room temp
                                            # and target temp is too large
                                            # This can happens when the price changes radically from one hour to the next
  
  day_transfer_charge           = 3.87      # Grid transfer cost in cent/kWh from 07 - 22
  night_transfer_charge         = 1.31      # Grid transfer cost in cent/kWh from 22 - 07

  state_update_timer            = 5        # How many seconds between two state updates

  #manual_override_end_time      = datetime.now()  # Defines when manual override will stop
  #manual_override_target_temp   = 23              # What temperature to set when manual override is active


  entity_id_climate_control = "climate.153931628243065_climate"
  entity_id_weather_forecast = "weather.forecast_home"
  entity_id_nordpool_sensor  = "sensor.nordpool_kwh_fi_eur_3_10_024"


  target_room_min_temperature_id = "input_number.target_room_min_temperature"
  target_room_temperature_id = "input_number.target_room_temperature"
  target_room_max_temperature_id = "input_number.target_room_max_temperature"
  
  min_mean_price_multiplier_id = "input_number.min_mean_price_multiplier"
  max_mean_price_multiplier_id = "input_number.max_mean_price_multiplier"
  
  min_absolute_price_id = "input_number.min_absolute_price"
  max_absolute_price_id = "input_number.max_absolute_price"
  
  min_state_change_time_id = "input_number.min_state_change_time"
  ignore_change_time_temp_diff_id = "input_number.ignore_change_time_temp_diff"
  
  day_transfer_charge_id = "input_number.day_transfer_charge"
  night_transfer_charge_id = "input_number.night_transfer_charge"

  #manual_override_end_time_id = "input_datetime.manual_override_end_time"

  # TODO: AC energy multiplier curve based on outside and inside temp difference. AC is more effective during hours when outside temp
  #       is higher, which can be used to make a better price estimation when we move from pure electricity pricing calculation to
  #       heat generation calculation for multiple heat sources (AC, direct electricity heating element, wood furnace, gas, ...)
  #       It also makes sense to calculate like this with only using AC, as it makes a real price difference depending on how
  #       effective the AC is during certain hours



  # Working variables
  last_state_change_time = 0


  def initialize(self):
    # Define all variables inside the instance of this class
    self.last_state_change_time = datetime.now() - timedelta(seconds=self.min_state_change_time+1)
    self.initialize_all_parameters()
    self.update_internal_parameters()

    # Define the starting time
    # now = datetime.datetime.now()

    # Schedule the function to run every state_update_timer seconds
    self.run_every(self.control_climate, "now", self.state_update_timer)

  def create_input_date(self, entity_id, name):
    # Check if the entity already exists
    entity_state = self.get_state(entity_id)
    # entity_state = None
    
    if entity_state is None:
      # Entity doesn't exist, so create it with the initial value
      self.log(f"Creating {entity_id} with initial value")
      now = datetime.now()
      self.set_state(entity_id, state="", attributes={
          "year": now.year,
          "month": now.month,
          "day": now.day,
          "hour": now.hour,
          "second": now.second,
          "friendly_name": name
      })

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

  def initialize_all_parameters(self):
    # Dynamically create or set default values for input_number entities only if they don't exist
    # self.log(f"Update all parameters")
    self.create_input_number(self.target_room_min_temperature_id, "Min Room Temperature", 18, 10, 30, 0.5)
    self.create_input_number(self.target_room_temperature_id, "Target Room Temperature", 23, 10, 30, 0.5)
    self.create_input_number(self.target_room_max_temperature_id, "Max Room Temperature", 24, 10, 30, 0.5)
    
    self.create_input_number(self.min_mean_price_multiplier_id, "Min Mean Price Multiplier", 0.5, 0.1, 2.0, 0.1)
    self.create_input_number(self.max_mean_price_multiplier_id, "Max Mean Price Multiplier", 1.5, 0.1, 2.0, 0.1)
    
    self.create_input_number(self.min_absolute_price_id, "Min Absolute Price", 5.0, 0.0, 100.0, 0.5)
    self.create_input_number(self.max_absolute_price_id, "Max Absolute Price", 30.0, 0.0, 100.0, 0.5)
    
    self.create_input_number(self.min_state_change_time_id, "Min State Change Time (sec)", 1800, 0, 3600, 60)
    self.create_input_number(self.ignore_change_time_temp_diff_id, "Temp Diff to Ignore Time", 2, 0, 10, 0.5)
    
    self.create_input_number(self.day_transfer_charge_id, "Electricity Grid Day Transfer Charge", 3.87, 0.0, 10.0, 0.1)
    self.create_input_number(self.night_transfer_charge_id, "Electricity Grid Night Transfer Charge", 1.31, 0.0, 10.0, 0.1)

    # self.create_input_date(self.manual_override_end_time_id, "Manual control end time")

    # manual_override_end_time
    #manual_override_target_temp   

    self.listen_event(self.change_state, event = "call_service")

    # Set up state listeners (callbacks) for when these values change
    self.listen_state(self.input_number_changed, self.target_room_min_temperature_id)
    self.listen_state(self.input_number_changed, self.target_room_temperature_id)
    self.listen_state(self.input_number_changed, self.target_room_max_temperature_id)
    
    self.listen_state(self.input_number_changed, self.min_mean_price_multiplier_id)
    self.listen_state(self.input_number_changed, self.max_mean_price_multiplier_id)
    
    self.listen_state(self.input_number_changed, self.min_absolute_price_id)
    self.listen_state(self.input_number_changed, self.max_absolute_price_id)
    
    self.listen_state(self.input_number_changed, self.min_state_change_time_id)
    self.listen_state(self.input_number_changed, self.ignore_change_time_temp_diff_id)
    
    self.listen_state(self.input_number_changed, self.day_transfer_charge_id)
    self.listen_state(self.input_number_changed, self.night_transfer_charge_id)

    # self.listen_state(self.input_datetime_changed, self.manual_override_end_time_id)


  def update_internal_parameters(self):
    # Update our local properties for ease of use
    self.target_room_min_temperature = float(self.get_state(self.target_room_min_temperature_id))
    self.target_room_temperature = float(self.get_state(self.target_room_temperature_id))
    self.target_room_max_temperature = float(self.get_state(self.target_room_max_temperature_id))

    self.min_mean_price_multiplier = float(self.get_state(self.min_mean_price_multiplier_id))
    self.max_mean_price_multiplier = float(self.get_state(self.max_mean_price_multiplier_id))

    self.min_absolute_price = float(self.get_state(self.min_absolute_price_id))
    self.max_absolute_price = float(self.get_state(self.max_absolute_price_id))

    self.min_state_change_time = int(self.get_state(self.min_state_change_time_id))
    self.ignore_change_time_temp_diff = float(self.get_state(self.ignore_change_time_temp_diff_id))

    self.day_transfer_charge = float(self.get_state(self.day_transfer_charge_id))
    self.night_transfer_charge = float(self.get_state(self.night_transfer_charge_id))

  def change_state(self,event_name,data, kwargs):
    entity_id = data["service_data"]["entity_id"]
    new_value = data["service_data"].get("value")

    # self.log(data)
    
    if entity_id == self.target_room_min_temperature_id:
        self.set_state(self.target_room_min_temperature_id, state=new_value)
        
    elif entity_id == self.target_room_temperature_id:
        self.set_state(self.target_room_temperature_id, state=new_value)
        
    elif entity_id == self.target_room_max_temperature_id:
        self.set_state(self.target_room_max_temperature_id, state=new_value)
        
    elif entity_id == self.min_mean_price_multiplier_id:
        self.set_state(self.min_mean_price_multiplier_id, state=new_value)
        
    elif entity_id == self.max_mean_price_multiplier_id:
        self.set_state(self.max_mean_price_multiplier_id, state=new_value)
        
    elif entity_id == self.min_absolute_price_id:
        self.set_state(self.min_absolute_price_id, state=new_value)
        
    elif entity_id == self.max_absolute_price_id:
        self.set_state(self.max_absolute_price_id, state=new_value)
        
    elif entity_id == self.min_state_change_time_id:
        self.set_state(self.min_state_change_time_id, state=new_value)
        
    elif entity_id == self.ignore_change_time_temp_diff_id:
        self.set_state(self.ignore_change_time_temp_diff_id, state=new_value)
        
    elif entity_id == self.day_transfer_charge_id:
        self.set_state(self.day_transfer_charge_id, state=new_value)
        
    elif entity_id == self.night_transfer_charge_id:
        self.set_state(self.night_transfer_charge_id, state=new_value)

    #elif entity_id == self.manual_override_end_time_id:
    #    new_time = data["service_data"].get("time")
    #    self.set_state(self.manual_override_end_time_id, state=new_value)

    #if(data["service"] == "turn_off" and data["service_data"]["entity_id"] == self.input_boolean):
    #    self.log(self.input_boolean + "switched off")
    #    self.set_state(self.input_boolean, state = "off")
    #if(data["service"] == "turn_on" and data["service_data"]["entity_id"] == self.input_boolean):
    #    self.log(self.input_boolean + "switched on")
    #    self.set_state(self.input_boolean, state = "on")


  def input_number_changed(self, entity, attribute, old, new, kwargs):
      # Log whenever an input_number value changes
      self.log(f"{entity} changed from {old} to {new}")
      
      # Update the internal values after the change
      self.update_internal_parameters()

      # Allow immediate AC state update
      self.last_state_change_time = datetime.now() - timedelta(seconds=self.min_state_change_time+1)

  def input_datetime_changed(self, entity, attribute, old, new, kwargs):
      # Log whenever an input_datetime value changes
      self.log(f"{entity} changed from {old} to {new}")
      
      # Update the internal values after the change
      self.update_internal_parameters()

      # Allow immediate AC state update
      self.last_state_change_time = datetime.now() - timedelta(seconds=self.min_state_change_time+1)


  def normalize_value(self, value_now, max_value, min_value):
    if max_value == min_value:
      raise ValueError("max_value and min_value cannot be the same value to avoid division by zero.")
    
    normalized_value = (value_now - min_value) / (max_value - min_value)
    
    # Clamp the value to be within the range [0, 1]
    normalized_value = max(0, min(1, normalized_value))
    
    return normalized_value


  def calculate_mean_value(self, item_list):
    # Calculate the mean value of the hourly prices
    if item_list:  # Check if the list is not empty
      mean_value = sum(item_list) / len(item_list)
    else:
      mean_value = 0  # or handle empty list case appropriately
    mean_value = round(mean_value, 1)
    return mean_value


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
      hourly_prices[i] = hourly_prices[i] + 0.41

    # Add the night / day transfer charge
    for i in range(len(hourly_prices)):
      if ( (i % 24) >= 22 or (i % 24) < 7):
        # Night transfer charge
        hourly_prices[i] = hourly_prices[i] + self.night_transfer_charge
      else:
        # Day transfer charge
        hourly_prices[i] = hourly_prices[i] + self.day_transfer_charge
      # Safety in case once in a blue moon we get negative prices
      # Setting it to 0 will avoid any strange calculations later on
      # This will have minimal effect in practice and will almost never be applied
      if (hourly_prices[i] < 0):
        hourly_prices[i] = 0

    # Round each price to one decimal place
    hourly_prices = [round(price, 1) for price in hourly_prices]

    return hourly_prices


  # Calculates the target temperature for this hour based on readings and price
  def calculate_target_temperature(self):
    inside_temperature = self.get_state(self.entity_id_climate_control, attribute="current_temperature")

    current_hour = datetime.now().hour
    hourly_prices = self.calculate_hourly_prices()
    mean_price = self.calculate_mean_value(hourly_prices)
    mean_price_min = mean_price * self.min_mean_price_multiplier
    mean_price_max = mean_price * self.max_mean_price_multiplier
    price_now = hourly_prices[current_hour]
    if (price_now < 0):
      price_now = 0
    self.log(f"Price now: {price_now}, Mean price {mean_price}")
    # self.log(f"Today+tomorrow full prices {len(hourly_prices)} items: {hourly_prices}")

    if (inside_temperature < self.target_room_min_temperature):
      return self.target_room_min_temperature
    
    if (inside_temperature > self.target_room_max_temperature):
      return self.target_room_max_temperature
    
    if (price_now > self.max_absolute_price):
      return self.target_room_min_temperature
    
    if (price_now < self.min_absolute_price):
      return self.target_room_max_temperature
    
    if (price_now > mean_price_max):
      return self.target_room_min_temperature
    
    if (price_now < mean_price_min):
      return self.target_room_max_temperature
    
    if (price_now >= mean_price):
      # Calculate linear curve down to min temp based on how much higher than mean_price we are right now
      # How much should we reduce ideal room temp based on how much over mean price we are?
      # Higher price means we will accept lower temperatures before starting AC
      temp_reduction = self.normalize_value(price_now, mean_price_max, mean_price) * (self.target_room_temperature - self.target_room_min_temperature)
      return self.target_room_temperature - temp_reduction
    
    if (price_now < mean_price):
      # Calculate linear curve up to max temp based on how much lower than mean_price we are right now
      temp_increase = self.normalize_value(price_now, mean_price, mean_price_min) * (self.target_room_max_temperature - self.target_room_temperature)
      return self.target_room_temperature + temp_increase
    
    return self.target_room_temperature
  

  def control_AC(self, target_temperature):
    inside_temperature = self.get_state(self.entity_id_climate_control, attribute="current_temperature")
    ac_power = self.get_state(self.entity_id_climate_control, attribute="power")
    ac_mode = self.get_state(self.entity_id_climate_control, attribute="power")
    ac_state = self.get_state(self.entity_id_climate_control, attribute="state")
    ac_fan_mode = self.get_state(self.entity_id_climate_control, attribute="fan_mode")
    ac_swing_mode = self.get_state(self.entity_id_climate_control, attribute="swing_mode")
    ac_current_target_temperature = self.get_state(self.entity_id_climate_control, attribute="temperature")
    ac_prompt_tone = self.get_state(self.entity_id_climate_control, attribute="prompt_tone")
    # self.log(f"AC state: {ac_state}")
    
    self.log(f"Room temp: {inside_temperature}, Target temp: {target_temperature}, AC temp: {ac_current_target_temperature}")
    self.log(f"Time since last state change: {datetime.now() - self.last_state_change_time}")

    if ( (datetime.now() - self.last_state_change_time) < timedelta(seconds=self.min_state_change_time) ):
      if ( (abs(ac_current_target_temperature - target_temperature)) < self.ignore_change_time_temp_diff ):
        # Not yet time for a scheduled state change and the temperature deviation is not large enough, don't do anything
        return

    if (inside_temperature >= target_temperature):
      # Make sure AC is shut down
      if (ac_state != "fan_only"):
        self.log(f"Turn off AC - Use fan only mode");
        self.last_state_change_time = datetime.now()
        self.call_service("climate/set_hvac_mode", entity_id=self.entity_id_climate_control, hvac_mode="fan_only")
        time.sleep(2)

      if (ac_fan_mode != "Silent"):
        self.log(f"Set fan to silent")
        self.call_service("climate/set_fan_mode", entity_id=self.entity_id_climate_control, fan_mode="Silent")
        time.sleep(2)

    else:
      # Make sure AC is running and has the correct target temperatures
      if (ac_power == False):
        self.log(f"Turn on AC");
        self.last_state_change_time = datetime.now()
        self.call_service("climate/turn_on", entity_id=self.entity_id_climate_control)
        time.sleep(2)
      
      if (target_temperature != ac_current_target_temperature):
        self.log(f"Set AC temperature to {target_temperature}");
        self.last_state_change_time = datetime.now()
        self.call_service("climate/set_temperature", entity_id=self.entity_id_climate_control, temperature=target_temperature)
        time.sleep(2)

      if (ac_state != "heat"):
        self.log(f"Set AC to heat")
        self.last_state_change_time = datetime.now()
        self.call_service("climate/set_hvac_mode", entity_id=self.entity_id_climate_control, hvac_mode="heat")
        time.sleep(2)

      if (ac_fan_mode != "Medium"):
        self.log(f"Set AC fan to Medium")
        self.last_state_change_time = datetime.now()
        self.call_service("climate/set_fan_mode", entity_id=self.entity_id_climate_control, fan_mode="Medium")
        time.sleep(2)

      if (ac_swing_mode != "Horizontal"):
        self.log(f"Set AC swing mode to Horizontal")
        self.last_state_change_time = datetime.now()
        self.call_service("climate/set_swing_mode", entity_id=self.entity_id_climate_control, swing_mode="Horizontal")
        time.sleep(2)


  def update_custom_sensors(self, target_temperature):
    # Update or create a custom sensor to store this data
    current_hour = datetime.now().hour
    hourly_prices = self.calculate_hourly_prices()
    price_now = hourly_prices[current_hour]
    
    ac_state = self.get_state(self.entity_id_climate_control, attribute="state")
    ac_on_off_state = 0
    self.log(f"Add state to history: {ac_state}")
    if (ac_state == "heat"):
      ac_on_off_state = 1
    self.set_state("sensor.ac_on_off_history", state=ac_on_off_state, attributes={
        "unit_of_measurement": "",
        "friendly_name": "AC activity history"
    })

    self.set_state("sensor.ac_target_temperature_history", state=target_temperature, attributes={
        "unit_of_measurement": "C",
        "friendly_name": "AC target temp history"
    })

    self.set_state("sensor.electricity_price", state=price_now, attributes={
        "unit_of_measurement": "c/kWh",
        "friendly_name": "Electricity price history"
    })




  def control_climate(self, kwargs):
    # 
    # self.call_service("climate/set_temperature", entity_id="climate.153931628243065_climate", temperature=21)
    # self.log("AC control updated")
    self.log(f"")
    target_temperature = self.calculate_target_temperature()
    # Round to closest half degree
    target_temperature = round(target_temperature * 2) / 2

    self.control_AC(target_temperature)
    self.update_custom_sensors(target_temperature)
  
