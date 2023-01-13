# homeassistant-binary-sensor-predictor
This Home Assistant integration creates a prediction for a binary entity on/off state based on its previously observed states.

Currently the only supported observable period is a day. The integration creates prediction for every 5 minutes (called time block) for the next 24 hours.

## How does it work?

Every time when the time block ends (currently every 5 minutes) the integration checks if the predicted entity was in `on` state in the ended time block. If it was `on` saves this information and use this information for predicting the next day. After running the integration for an observed period (currently 24 hours) the integration starts predict the probability for the current time block based on the previous day. When the 2nd day passes it will modifies the prediction values based on the first and the second day to. As the time pass more and more observation collected and predicted probabilities will be closer to the reality.

Initially the probability of `on` state is `0`. For every time block $T$ the integration use the following formula to update the probability of an ended time block:

$$
P_{T}(state=on)_{t} := P_{T}(state=on)_{t-1} * f + S * (1 - f)
$$

In the formula:
- $P_{T}(state=on)_{t}$ is the updated probability for $T$ time block
- $P_{T}(state=on)_{t-1}$ is the previously calculated probability for $T$ time block
- $f$ is the fading parameter
- $S$ is `1` if the observed (and predicted) sensor was in `on` state in the ended time block otherwise `0`

## Fading parameter
The fading parameter should be between `0..1`. This controls how much the past is important. Higher values means sensor will use past observations with much higher rate in the prediction, which means the predictor sensor will learn the new patterns changes slower. Lower values means the sensor forgets the past easier and use the observations from the near future with much higher weight. This will make the predictor more sensitive to changes and makes it faster to learn new patterns but could also spoils the predictions if there is an outlier day.

## Threshold parameter
The integration contains a threshold parameter which defines the minimum calculated probability when the predictor sensor state becomes `on`. If the calculated probability for the current time block is less then the threshold the predictor sensor state will be `off`.

## Using predictions
The integration provides a `probabilities` attribute in the sensor. This attribute is an array. The first element of the array is the predicted probability for the current time block, the second element is for the next time block and so on. As the time goes by the integration rotates the probabilities array so the current time block will always be the first element.

So at time $T$ you want to know the predicted value for the $T + 15 minute$ you can get from the `state_attr("binary_sensor.predictor", "probabilities")[15 // 5]`.

## What is this good for?
If there is recurring event which requires some kind of early starting of an automation you can use this integration. The motivation of creating this integration is a good example: If you have an underfloor heating system which takes several hours to heat up the bathroom with a couple of °C and you want to start heating 2 hours earlier than you will use the bathroom you can use the predictions when to start the heating. You just only need a binary sensor which reports `on` state whenever you have a bath (e.g: when a humidity sensor reads high humidity in the bathroom). The prediction will be automatically adjusted whenever your bathing habits changes and by that the heating can also change automatically based on that without any intervention.
