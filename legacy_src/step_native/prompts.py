"""STEP Supplement A.1: separate native tasks, no joint Event/FSG JSON prompt.

Paper's INST/image/video markup is rendered by Qwen's own chat template.
Source reference_sources/step_supp_pages.txt PDF1–3. Examples retained, only
objects/narratives substituted. Instance-specific referents disambiguate same-class objects.
"""
NARRATIVE='Describe the keyframe of the video in one sentence, ensuring to include all main objects within the scene.'
OBJECTS='''From the given sentence, the task is to extract meaningful objects. Note that the object is the entity or noun that being described in the sentence. Let’s take a few examples to understand how to extract meaningful objects.
Question: Given the sentence “Children play with red toys in the yard,” extract meaningful objects.
Answer: Meaningful objects are [children, toys, yard].
Question: Given the sentence “A beautiful woman walking a dog on top of a beach,” extract meaningful objects.
Answer: Meaningful objects are [woman, dog, beach].
Question: Given the sentence “A mix of black and white cat jumps over a old fence,” extract meaningful objects.
Answer: Meaningful objects are [cat, fence].
Please answer the following question.
Question: Given the sentence “[{narrative}],” extract meaningful objects.
Answer:'''
INSTANCES='''Given the object name: [{label}], if there is more than one, please provide the quantity and describe each instance of [{label}] with a corresponding unique attribute. The unique attribute should be something that only one instance has while the others do not. Use the following format for the output:
Object: [{label}]
Quantity: [number]
1. [{label}]1: [distinct unique attribute]
2. [{label}]2: [distinct unique attribute]
...'''
CLASSIFY='''Given the object: [{referent}], determine if it is a static object or a dynamic object. Note that static objects refer to background objects that may not move or change observably within a short time while dynamic objects are the opposite. If the object is static, print ‘Static’, otherwise print ‘Dynamic’, no explanation is needed.'''
ATTR_NARRATIVE='''Given the object: [{referent}], describe its attributes in the scene using one or two sentences that primarily include adjectives or present participles (-ing forms). Avoid any irrelevant details or complex explanations.'''
ATTR_EXTRACT='''For the given sentence, the task is to extract meaningful attributes for the given object. Each attribute should include its type and value. Let’s take a few examples to understand how to extract meaningful attributes.
Question: Given the sentence “A woman with long and blonde hair is sitting on a park bench,” extract meaningful attributes for the object “woman”.
Answer: [“object”:“woman”, “attributes”:[“hair”:“long and blonde”, “status”:“sitting”]]
Question: Given the sentence “A tall man in a red jacket is walking down the street,” extract meaningful attributes for the object “man”.
Answer: [“object”:“man”, “attributes”:[“height”:“tall”, “clothing”:“red jacket”, “action”:“walking”]]
Question: Given the sentence “The blue car is parked,” extract meaningful object label and attributes for the object “car”
Answer: [“object”:“car”, “attributes”:[“color”:“blue”, “status”:“parked”]]
Please answer the following question.
Question: Given the sentence “[{narrative}],” extract meaningful attributes for the object “[{referent}]”
Answer:'''
REL_NARRATIVE='''Given the object: [{referent}] in the provided image, describe all spatial or contact relationship between [{referent}] and other objects [{others}] in the image. Ensure the subject of every sentence is [{referent}], and do not include detailed descriptions of other objects.'''
REL_EXTRACT='''From the given sentence, the task is to extract meaningful triplets formed as <subject, predicate, object>. Note that the subject must be the given object, and the object is the entity or noun that is affected by the action or is receiving the action. The predicate is a verb or adjective without auxiliary verb, and is represented without the tense (e.g., are, being). Let’s take a few examples to understand how to extract meaningful triplets.
Question: Given the sentence “a slice of bread is covered with a sour cream and quacamole,” extract meaningful triplets for the given object “bread”.
Answer: Meaningful triplets are <bread, covered with, sour cream>, <bread, covered with, guacamole>.
Question: Given the sentence “A clock sitting on a floor next to a woman’s feet,” extract meaningful triplets for the given object “clock”.
Answer: Meaningful triplets are <clock, sitting on, floor>, <clock, next to, feet>.
Question: Given the sentence “One person sits in a chair looking at her phone while another rests on the couch,” extract meaningful triplets for the given object “person”.
Answer: Meaningful triplets are <person, sits in, chair>, <person, looking at, phone>, <person, rests on, couch>.
Please answer the following question.
Question: Given the sentence “[{narrative}],” extract meaningful triplets for the given object [{referent}].
Answer:'''
